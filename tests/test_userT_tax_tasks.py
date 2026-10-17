"""Functional coverage for SCRUM-599, SCRUM-650 and SCRUM-656.

These tests use the persisted fiscal-document tables and the real period/report
services. The only stubbed value is historical sales debit, because this suite
is focused on input documents and does not manufacture sales records.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4
from openpyxl import load_workbook
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from app.models.tenant.registry import build_tenant_metadata
from app.schemas.fiscal import FiscalDocumentCreate, ImportBatchCreate
from app.schemas.taxation import TaxProfileInput
from app.services import fiscal_documents, reports, taxation, tax_period

def _user(schema):
    return SimpleNamespace(
        id=uuid4(), company_id=uuid4(),
        company=SimpleNamespace(is_active=True, schema_name=schema, name=schema),
        username="userT-test",
    )

def _profile():
    return TaxProfileInput(
        name="userT functional test profile",
        jurisdiction="TEST",
        regime="CONFIGURABLE",
        default_currency="USD",
        effective_from=date(2026, 1, 1),
        version_id="userT-v1",
        taxes=[{"tax_code": "TAX_TEST", "name": "Configured test tax", "category": "TAXABLE"}],
        rules=[{
            "scope": "INPUT_TAX", "tax_code": "TAX_TEST",
            "condition": {"field": "tax_category", "operator": "eq", "value": "TAXABLE"},
            "result": {"eligible_for_input_credit": True},
            "version_id": "userT-input-credit-v1",
        }],
    )

def _setup_db(schemas):
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def sqlite_now(connection, _record):
        connection.create_function("now", 0, lambda: datetime.now(timezone.utc).isoformat(sep=" "))

    with engine.begin() as connection:
        connection.execute(text('ATTACH DATABASE ":memory:" AS "global"'))

        for schema in schemas:
            connection.execute(text(f'ATTACH DATABASE ":memory:" AS "{schema}"'))
            build_tenant_metadata(schema).create_all(connection)

    return engine, sessionmaker(bind=engine)()

def _create_document(user, db, *, status="ACTIVE", total="130", currency="USD", source_row=1):
    batch = fiscal_documents.create_import_batch(
        ImportBatchCreate(source_type="CSV", filename="userT.csv", total_rows=1), user, db
    )

    return fiscal_documents.create_document(FiscalDocumentCreate(
        document_type="INVOICE", direction="INPUT", issue_date=date(2026, 1, 10),
        document_number="DOC-001", series="SER-A", authorization_number="AUTH-001",
        issuer_name="Proveedor de prueba", issuer_tax_identifier="ID-001",
        currency=currency, subtotal=Decimal("100"), taxable_base=Decimal("100"),
        total_tax=Decimal("30"), total=Decimal(total), status=status,
        import_batch_id=batch["id"], source_row=source_row,
        original_identifier="ORIGINAL-001",
        taxes=[{"tax_code": "TAX_TEST", "tax_type": "percentage", "category": "TAXABLE",
                "taxable_base": Decimal("100"), "amount": Decimal("30")}],
        lines=[
            {"description": "Línea 1", "taxable_base": Decimal("50"), "total": Decimal("65"),
             "taxes": [{"tax_code": "TAX_TEST", "tax_type": "percentage", "category": "TAXABLE",
                        "taxable_base": Decimal("50"), "amount": Decimal("10")}]},
            {"description": "Línea 2", "taxable_base": Decimal("50"), "total": Decimal("65"),
             "taxes": [{"tax_code": "TAX_TEST", "tax_type": "percentage", "category": "TAXABLE",
                        "taxable_base": Decimal("50"), "amount": Decimal("20")}]},
        ],
    ), user, db)

def test_scrum650_real_period_credit_excludes_cancelled_and_deduplicates(monkeypatch):
    schema = "tenant_userT_credit"
    engine, db = _setup_db([schema])
    user = _user(schema)

    try:
        taxation.put_tax_profile(_profile(), user, db)
        active = _create_document(user, db)
        _create_document(user, db, status="CANCELLED", source_row=2, total="130")
        monkeypatch.setattr(tax_period.analytics, "get_fiscal_debit", lambda *_a, **_k: {"fiscal_debit": Decimal("100")})

        result = tax_period.calculate_period(
            user, db, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31), include_details=True
        )

        assert result["input_documents_count"] == 1
        assert result["tax_credit"] == Decimal("30.00")
        assert result["tax_payable"] == Decimal("70.00")
        assert len(result["details"]) == 2
        assert all(detail["document_id"] == active["id"] for detail in result["details"])

    finally:
        db.close()
        engine.dispose()

def test_scrum650_real_tenant_isolation_and_currency_validation(monkeypatch):
    schemas = ["tenant_userT_a", "tenant_userT_b"]
    engine, db = _setup_db(schemas)
    user_a, user_b = (_user(schema) for schema in schemas)

    try:
        taxation.put_tax_profile(_profile(), user_a, db)
        taxation.put_tax_profile(_profile(), user_b, db)
        _create_document(user_a, db, total="130")
        _create_document(user_b, db, total="230")
        monkeypatch.setattr(tax_period.analytics, "get_fiscal_debit", lambda *_a, **_k: {"fiscal_debit": Decimal("0")})

        result_a = tax_period.calculate_period(user_a, db, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))
        result_b = tax_period.calculate_period(user_b, db, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))

        assert result_a["tax_credit"] == result_b["tax_credit"] == Decimal("30.00")
        assert result_a["input_documents_count"] == result_b["input_documents_count"] == 1

    finally:
        db.close()
        engine.dispose()

def test_scrum599_scrum656_real_xlsx_content_for_both_regimes(monkeypatch):
    schema = "tenant_userT_report"
    engine, db = _setup_db([schema])
    user = _user(schema)

    try:
        taxation.put_tax_profile(_profile(), user, db)
        document = _create_document(user, db)
        monkeypatch.setattr(reports, "_get_fiscal_debit_for_report", lambda *_a, **_k: {"fiscal_debit": Decimal("100")})
        monkeypatch.setattr(tax_period.analytics, "get_fiscal_debit", lambda *_a, **_k: {"fiscal_debit": Decimal("100")})

        for regime in ("SMALL_TAXPAYER", "GENERAL_VAT"):
            workbook_data = reports.build_tax_report(
                user, db, regime=regime, period="custom",
                start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
            )
            payload = reports.generate_tax_report(workbook_data, user, db)[0]
            workbook = load_workbook(BytesIO(payload), data_only=True)

            assert workbook.sheetnames == ["Compras", "Ventas", "Resumen"]

            purchases = workbook["Compras"]

            assert purchases.max_row == 2
            assert purchases.cell(2, 1).value == 1
            assert purchases.cell(2, 2).value.date() == date(2026, 1, 10)
            assert purchases.cell(2, 3).value == "INVOICE"

            if regime == "SMALL_TAXPAYER":
                assert purchases.cell(2, 4).value == "DOC-001"
                assert purchases.cell(2, 5).value == "ID-001"
                assert purchases.cell(2, 6).value == "Proveedor de prueba"
                assert purchases.cell(2, 7).value == 130
                assert workbook["Resumen"].cell(4, 2).value == 100

            else:
                assert purchases.cell(2, 4).value == "SER-A / AUTH-001"
                assert purchases.cell(2, 5).value == "DOC-001"
                assert purchases.cell(2, 6).value == "ID-001"
                assert purchases.cell(2, 7).value == "Proveedor de prueba"
                assert purchases.cell(2, 9).value == 30
                assert purchases.cell(2, 10).value == 130
                assert workbook["Resumen"].cell(3, 2).value == 100
                assert workbook["Resumen"].cell(5, 2).value == 30

    finally:
        db.close()
        engine.dispose()