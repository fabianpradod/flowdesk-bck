from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
import pytest
from sqlalchemy import Boolean, Column, DateTime, MetaData, Numeric, String, Table, create_engine, insert
from sqlalchemy.orm import sessionmaker
from app.services import analytics as analytics_service
from app.utils.exceptions import AppError

@pytest.fixture
def fiscal_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    metadata = MetaData()
    sales = Table("venta", metadata,
        Column("id", String, primary_key=True), Column("fecha", DateTime, nullable=False),
        Column("subtotal", Numeric(10, 2), nullable=False), Column("impuesto", Numeric(10, 2), nullable=False),
        Column("es_exenta", Boolean, nullable=False), Column("estado", String, nullable=False))
    sales_b = Table("venta_b", metadata,
        Column("id", String, primary_key=True), Column("fecha", DateTime, nullable=False),
        Column("subtotal", Numeric(10, 2), nullable=False), Column("impuesto", Numeric(10, 2), nullable=False),
        Column("es_exenta", Boolean, nullable=False), Column("estado", String, nullable=False))
    metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    monkeypatch.setattr(
        analytics_service,
        "_analytics_tables",
        lambda user: {"venta": sales if user.company.schema_name.endswith("a" * 32) else sales_b},
    )
    yield db, sales, sales_b
    db.close()
    engine.dispose()

def _user(suffix="a"):
    return SimpleNamespace(company=SimpleNamespace(schema_name="tenant_" + suffix * 32))

def _sale(sales, *, day, subtotal, tax, exempt=False, state="completada"):
    return insert(sales).values(id=str(uuid4()), fecha=datetime(2026, 8, day, 12),
        subtotal=Decimal(subtotal), impuesto=Decimal(tax), es_exenta=exempt, estado=state)

def _calculate(db):
    return analytics_service.get_fiscal_debit(_user(), db, period="custom",
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 31))

def test_fiscal_debit_includes_taxable_sales_and_excludes_exempt_tax(fiscal_db):
    db, sales, _sales_b = fiscal_db
    db.execute(_sale(sales, day=2, subtotal="100.00", tax="12.00"))
    db.execute(_sale(sales, day=3, subtotal="50.00", tax="0.00", exempt=True))
    db.commit()
    result = _calculate(db)
    assert result["sales_count"] == 2
    assert result["taxable_subtotal"] == Decimal("100.00")
    assert result["exempt_subtotal"] == Decimal("50.00")
    assert result["fiscal_debit"] == Decimal("12.00")

def test_fiscal_debit_ignores_non_final_sales(fiscal_db):
    db, sales, _sales_b = fiscal_db
    db.execute(_sale(sales, day=2, subtotal="100.00", tax="12.00", state="borrador"))
    db.execute(_sale(sales, day=3, subtotal="80.00", tax="9.60", state="cancelada"))
    db.commit()
    result = _calculate(db)
    assert result["sales_count"] == 0
    assert result["fiscal_debit"] == Decimal("0.00")

def test_fiscal_debit_returns_zero_for_an_empty_period(fiscal_db):
    result = _calculate(fiscal_db[0])
    assert result["sales_count"] == 0
    assert result["taxable_subtotal"] == Decimal("0.00")
    assert result["exempt_subtotal"] == Decimal("0.00")
    assert result["fiscal_debit"] == Decimal("0.00")

def test_fiscal_debit_rejects_invalid_custom_period(fiscal_db):
    with pytest.raises(AppError, match="Custom analytics period"):
        analytics_service.get_fiscal_debit(_user(), fiscal_db[0], period="custom", start_date=date(2026, 8, 1))
    with pytest.raises(AppError, match="start_date must be before end_date"):
        analytics_service.get_fiscal_debit(_user(), fiscal_db[0], period="custom",
            start_date=date(2026, 8, 31), end_date=date(2026, 8, 1))

def test_fiscal_debit_isolated_by_company(fiscal_db):
    db, sales_a, sales_b = fiscal_db
    db.execute(_sale(sales_a, day=2, subtotal="100.00", tax="12.00"))
    db.execute(_sale(sales_b, day=2, subtotal="500.00", tax="60.00"))
    db.commit()

    debit_a = analytics_service.get_fiscal_debit(_user("a"), db, period="custom",
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 31))
    debit_b = analytics_service.get_fiscal_debit(_user("b"), db, period="custom",
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 31))

    assert debit_a["fiscal_debit"] == Decimal("12.00")
    assert debit_b["fiscal_debit"] == Decimal("60.00")