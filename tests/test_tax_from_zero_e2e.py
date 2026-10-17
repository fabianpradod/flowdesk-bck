"""Principal from-zero integration flow using only existing taxation layers."""

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from app.models.tenant.registry import build_tenant_metadata
from app.schemas.fiscal import ImportMappingCreate, ImportPreviewOptions
from app.schemas.taxation import TaxCalculationRequest, TaxProfileInput, TaxableOperationInput
from app.services import imports, reports, taxation, tax_period

def test_new_tenant_configure_import_classify_period_and_report(monkeypatch):
    tenant = SimpleNamespace(company_id=uuid4(), company=SimpleNamespace(is_active=True, schema_name="tenant_e2e"))
    profile_input = TaxProfileInput(
        name="Configurable test profile", jurisdiction="TEST", regime="CONFIGURABLE", default_currency="USD",
        effective_from=date(2026, 1, 1), version_id="test-v1",
        taxes=[{"tax_code": "VAT_TEST", "name": "Configured test tax", "default_rate": "10", "category": "STANDARD"},
               {"tax_code": "RET_TEST", "name": "Configured retention", "category": "WITHHOLDING"}],
        rules=[
            {"scope": "CLASSIFICATION", "priority": 1, "condition": {"field": "document_direction", "operator": "eq", "value": "INPUT"},
             "result": {"direction": "INPUT"}, "version_id": "class-input"},
            {"scope": "CLASSIFICATION", "priority": 2, "condition": {"field": "document_direction", "operator": "eq", "value": "OUTPUT"},
             "result": {"direction": "OUTPUT"}, "version_id": "class-output"},
            {"scope": "INPUT_TAX", "tax_code": "VAT_TEST", "condition": {"field": "tax_category", "operator": "eq", "value": "TAXABLE"},
             "result": {"eligible_for_input_credit": True}, "version_id": "credit-rule"},
            {"scope": "WITHHOLDING", "tax_code": "RET_TEST", "condition": {"field": "withholding_type", "operator": "eq", "value": "configured"},
             "result": {"withholding_effect": "INFORMATIONAL"}, "version_id": "retention-rule"},
        ],
    )

    # Tenant-scoped validation is non-persistent and precedes configuration use.
    original_get_profiles = taxation.get_tax_profiles
    monkeypatch.setattr(taxation, "get_tax_profiles", lambda _user, _db: [])
    validation = taxation.validate_tax_profile(profile_input, tenant, object())

    assert validation["valid"] is True and validation["errors"] == []

    mapping = ImportMappingCreate(
        name="Generic test CSV", source_type="CSV",
        mapping={"Type": "document_type", "Date": "issue_date", "Direction": "direction", "Currency": "currency",
                 "Base": "taxes[0].taxable_base", "Tax": "taxes[0].amount", "Tax type": "taxes[0].tax_type", "Code": "taxes[0].tax_code",
                 "Category": "taxes[0].category", "Retention": "taxes[1].amount", "Retention code": "taxes[1].tax_code",
                 "Retention type code": "taxes[1].tax_type", "Retention category": "taxes[1].category", "Retention flag": "taxes[1].is_withholding",
                 "Retention type": "taxes[1].withholding_type", "Retention effect": "taxes[1].withholding_effect",
                 "Total": "total"},
    )

    assert mapping.source_type == "CSV"

    csv = ("Type,Date,Direction,Currency,Base,Tax,Tax type,Code,Category,Retention,Retention code,Retention type code,Retention category,Retention flag,Retention type,Retention effect,Total\n"
           "INVOICE,2026-01-10,OUTPUT,USD,1000,100,percentage,VAT_TEST,TAXABLE,,,,,,,,1100\n"
           "INVOICE,2026-01-12,INPUT,USD,500,50,percentage,VAT_TEST,TAXABLE,5,RET_TEST,percentage,WITHHOLDING,true,configured,INFORMATIONAL,555\n"
           "INVOICE,2026-01-13,INPUT,USD,300,0,percentage,VAT_TEST,ZERO_RATED,,,,,,,,300\n"
           "INVOICE,2026-01-14,INPUT,USD,200,0,percentage,VAT_TEST,EXEMPT,,,,,,,,200\n"
           "INVOICE,2026-01-15,INPUT,USD,100,0,percentage,VAT_TEST,NON_TAXABLE,,,,,,,,100\n").encode()
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def sqlite_now(connection, _record):
        connection.create_function("now", 0, lambda: datetime.now(timezone.utc).isoformat(sep=" "))

    with engine.begin() as connection:
        connection.execute(text('ATTACH DATABASE ":memory:" AS "global"'))
        connection.execute(text('ATTACH DATABASE ":memory:" AS "tenant_e2e"'))
        build_tenant_metadata("tenant_e2e").create_all(connection)

    db = sessionmaker(bind=engine)()
    monkeypatch.setattr(taxation, "get_tax_profiles", original_get_profiles)

    taxation.put_tax_profile(profile_input, tenant, db)

    profile = taxation.resolve_current_profile(tenant, db, date(2026, 1, 1))
    mapping_result = imports.create_mapping(mapping, tenant, db)
    uploaded = imports.upload("test-tax.csv", csv, "text/csv", tenant, db)
    options = ImportPreviewOptions(mapping_id=mapping_result["id"])
    preview = imports.preview(uploaded["id"], options, tenant, db)

    assert preview["rows_detected"] == 5 and preview["rows_valid"] == 5

    validated = imports.validate_batch(uploaded["id"], options, tenant, db)

    assert validated["status"] == "VALIDATED"

    imported = imports.execute(uploaded["id"], options, tenant, db)

    assert imported["status"] == "IMPORTED" and imported["imported"] == 5

    documents = __import__("app.services.fiscal_documents", fromlist=["list_documents"]).list_documents(tenant, db)

    assert len(documents) == 5
    assert all(document["import_batch_id"] == uploaded["id"] for document in documents)

    retention_document = next(document for document in documents if any(tax["is_withholding"] for tax in document["taxes"]))

    assert retention_document["source_row"] == 3

    before_simulation = len(documents)
    simulation = taxation.calculate_tax(tenant, db, TaxCalculationRequest(
        as_of=date(2026, 1, 12), profile_version="test-v1", tax_debit=Decimal("100"),
        operations=[TaxableOperationInput(
            tax_amount=Decimal("50"), taxable_base=Decimal("500"), tax_category="TAXABLE",
            tax_code="VAT_TEST", document_direction="INPUT", operation_date=date(2026, 1, 12),
        )],
    ))

    assert simulation.tax_credit == Decimal("50")
    assert simulation.tax_payable == Decimal("50")
    assert len(__import__("app.services.fiscal_documents", fromlist=["list_documents"]).list_documents(tenant, db)) == before_simulation

    monkeypatch.setattr(tax_period, "resolve_current_profile", lambda *_args: profile)
    monkeypatch.setattr(tax_period.analytics, "get_fiscal_debit", lambda *_args, **_kwargs: {"fiscal_debit": Decimal("100")})
    period = tax_period.calculate_period(tenant, db, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31), include_details=True)

    assert period["tax_debit"] == Decimal("100")
    assert period["tax_credit"] == Decimal("50")
    assert period["net_tax"] == Decimal("50")
    assert period["tax_payable"] == Decimal("50")
    assert period["withholding_tax"] == Decimal("5")

    summary = reports._build_tax_summary("GENERAL_VAT", [], {"fiscal_debit": Decimal("100")}, period_result=period, input_documents=[retention_document])

    assert summary.rows[1][1] == Decimal("100.00")
    assert summary.rows[3][1] == Decimal("50.00")
    assert summary.rows[4][1] == Decimal("50.00")

    monkeypatch.setattr(reports, "_get_fiscal_debit_for_report", lambda *_args, **_kwargs: {"fiscal_debit": Decimal("100")})
    report = reports.build_tax_report(tenant, db, regime="GENERAL_VAT", start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))

    assert [sheet.name for sheet in report.sheets] == ["Compras", "Ventas", "Resumen"]
    assert len(report.sheets[0].rows) == 4
    assert report.sheets[2].rows[3][1] == Decimal("50.00")