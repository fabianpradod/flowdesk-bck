from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from sqlalchemy import Column, Date, MetaData, String, Table, create_engine, insert
from sqlalchemy.orm import sessionmaker
import pytest
from app.services import analytics, fiscal_documents, tax_period
from app.taxation import TaxDefinition, TaxProfile, TaxRule
from app.utils.exceptions import AppError

def _profile():
    return TaxProfile(None, None, date(2026, 1, 1), taxes=(TaxDefinition("VAT", "Input", category="TAXABLE"),), rules=(TaxRule(
        {"field": "tax_category", "operator": "eq", "value": "TAXABLE"}, scope="INPUT_TAX",
        result={"eligible_for_input_credit": True}),))

@pytest.fixture
def period_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    documents = Table("fiscal_document", metadata, Column("id", String, primary_key=True), Column("direction", String), Column("issue_date", Date), Column("currency", String), Column("status", String))
    metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    document_id = str(uuid4())
    db.execute(insert(documents).values(id=document_id, direction="INPUT", issue_date=date(2026, 1, 15), currency="USD", status="ACTIVE")); db.commit()
    user = SimpleNamespace(company_id=uuid4(), company=SimpleNamespace(is_active=True, schema_name="tenant_" + "a" * 32))
    monkeypatch.setattr(tax_period, "get_tenant_tables", lambda _schema: {"fiscal_document": documents})
    monkeypatch.setattr(tax_period, "resolve_current_profile", lambda *_args: _profile())
    monkeypatch.setattr(analytics, "get_fiscal_debit", lambda *_args, **_kwargs: {"fiscal_debit": Decimal("100")})
    monkeypatch.setattr(fiscal_documents, "get_document", lambda *_args, **_kwargs: {
        "id": document_id, "issue_date": date(2026, 1, 15), "taxes": [{"id": "component-1", "tax_code": "VAT", "category": "TAXABLE", "amount": Decimal("40")}], "lines": [],
    })

    yield db, user

    db.close()

def test_period_service_combines_historical_debit_and_persisted_input_credit(period_db):
    db, user = period_db
    result = tax_period.calculate_period(user, db, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31), include_details=True)

    assert result["tax_debit"] == Decimal("100")
    assert result["tax_credit"] == Decimal("40")
    assert result["tax_payable"] == Decimal("60")
    assert result["input_documents_count"] == 1
    assert result["eligible_tax_components_count"] == 1
    assert result["details"][0]["tax_component_id"] == "component-1"

def test_period_service_keeps_prior_carry_forward_as_engine_result(period_db):
    db, user = period_db
    result = tax_period.calculate_period(user, db, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31), prior_carry_forward=Decimal("50"))

    assert result["tax_payable"] == Decimal("10")
    assert result["carry_forward"] == 0

def test_period_service_rejects_mixed_input_currencies(period_db):
    db, user = period_db
    documents = tax_period.get_tenant_tables(user.company.schema_name)["fiscal_document"]
    db.execute(insert(documents).values(id=str(uuid4()), direction="INPUT", issue_date=date(2026, 1, 20), currency="EUR", status="ACTIVE")); db.commit()

    with pytest.raises(AppError, match="currencies"):
        tax_period.calculate_period(user, db, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))

def test_cancelled_document_is_not_used_without_status_rule(period_db):
    db, user = period_db
    documents = tax_period.get_tenant_tables(user.company.schema_name)["fiscal_document"]
    db.execute(documents.update().values(status="CANCELLED")); db.commit()
    result = tax_period.calculate_period(user, db, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))

    assert result["input_documents_count"] == 0 and result["tax_credit"] == 0