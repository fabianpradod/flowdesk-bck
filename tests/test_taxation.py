from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
import pytest
from pydantic import ValidationError
import app.services.commercial as commercial_service
from app.models.tenant.registry import build_tenant_metadata
from app.schemas.commercial import SaleCreate, TaxConfigurationUpdate

SCHEMA_NAME = "tenant_" + "b" * 32

class FakeResult:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

class FakeDB:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.statements = []
        self.commits = 0

    def execute(self, statement):
        self.statements.append(statement)
        return FakeResult(self.rows.pop(0) if self.rows else [])

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

def test_tax_configuration_is_a_tenant_table_and_sale_keeps_tax_snapshot():
    metadata = build_tenant_metadata(SCHEMA_NAME)

    assert f"{SCHEMA_NAME}.configuracion_tributaria" in metadata.tables
    sale = metadata.tables[f"{SCHEMA_NAME}.venta"]
    assert sale.c.tasa_impuesto.nullable is False
    assert sale.c.es_exenta.nullable is False

def test_tax_rate_is_validated_at_the_api_boundary():
    with pytest.raises(ValidationError):
        TaxConfigurationUpdate(tasa_impuesto=Decimal("100.01"))
    with pytest.raises(ValidationError):
        TaxConfigurationUpdate(tasa_impuesto=Decimal("-0.01"))

def test_sale_schema_marks_an_exempt_operation():
    sale = SaleCreate(items=[{"producto_id": uuid4(), "cantidad": "1"}], es_exenta=True)

    assert sale.es_exenta is True

@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal("1.005"), Decimal("1.01")),
        (Decimal("1.004"), Decimal("1.00")),
        (Decimal("19.995"), Decimal("20.00")),
    ],
)
def test_money_rounding_uses_decimal_half_up(amount, expected):
    assert commercial_service._round_money(amount) == expected

def test_tax_rate_defaults_to_zero_when_a_legacy_tenant_has_no_configuration():
    metadata = build_tenant_metadata(SCHEMA_NAME)
    config = metadata.tables[f"{SCHEMA_NAME}.configuracion_tributaria"]

    assert commercial_service._get_tax_rate(FakeDB([[]]), config) == Decimal("0")

def test_tax_configuration_update_persists_a_tenant_specific_rate(monkeypatch):
    metadata = build_tenant_metadata(SCHEMA_NAME)
    tables = {table.name: table for table in metadata.tables.values() if table.schema == SCHEMA_NAME}
    monkeypatch.setattr(commercial_service, "_tenant_tables", lambda _user: tables)
    db = FakeDB([[]])

    result = commercial_service.update_tax_configuration(
        TaxConfigurationUpdate(tasa_impuesto=Decimal("13.00")),
        SimpleNamespace(),
        db,
    )

    assert result == {"tasa_impuesto": Decimal("13.00")}
    assert db.commits == 1
    params = db.statements[-1].compile().params
    assert params["tasa_impuesto"] == Decimal("13.00")

@pytest.mark.parametrize(
    ("rate", "subtotal", "expected_tax"),
    [
        (Decimal("0.00"), Decimal("100.00"), Decimal("0.00")),
        (Decimal("5.00"), Decimal("100.00"), Decimal("5.00")),
        (Decimal("12.00"), Decimal("100.00"), Decimal("12.00")),
        (Decimal("12.00"), Decimal("15.35"), Decimal("1.84")),
        (Decimal("12.00"), Decimal("15.375"), Decimal("1.85")),
        (Decimal("15.00"), Decimal("33.33"), Decimal("5.00")),
        (Decimal("21.00"), Decimal("99.99"), Decimal("21.00")),
        (Decimal("100.00"), Decimal("50.00"), Decimal("50.00")),
    ],
)
def test_tax_calculation_across_different_rates(rate, subtotal, expected_tax):
    """SCRUM-528 y SCRUM-529: Validar diferentes escenarios de tasas y calculo tributario."""
    tax = commercial_service._round_money(subtotal * rate / commercial_service.MAX_TAX_RATE)
    assert tax == expected_tax

@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal("0.000"), Decimal("0.00")),
        (Decimal("0.0049"), Decimal("0.00")),
        (Decimal("0.0050"), Decimal("0.01")),
        (Decimal("0.0051"), Decimal("0.01")),
        (Decimal("100.125"), Decimal("100.13")),
        (Decimal("100.1249"), Decimal("100.12")),
        (Decimal("99999999.994"), Decimal("99999999.99")),
    ],
)
def test_monetary_rounding_edge_cases(amount, expected):
    """SCRUM-530: Probar precision y casos limite de redondeos monetarios."""
    assert commercial_service._round_money(amount) == expected

def test_exempt_sale_produces_zero_tax_with_preserved_rate(monkeypatch):
    """SCRUM-502 y SCRUM-528: Operaciones exentas producen 0 de impuesto pero conservan la tasa del tenant."""
    product_id = uuid4()
    product = {
        "id": product_id,
        "nombre": "Exempt Product",
        "precio_venta": Decimal("100.00"),
        "stock_actual": Decimal("10"),
        "stock_minimo": Decimal("1"),
        "is_active": True,
    }
    db = FakeDB([[product], [{"tasa_impuesto": Decimal("12.00")}]] )
    user = SimpleNamespace(
        id=uuid4(),
        company_id=uuid4(),
        company=SimpleNamespace(is_active=True, schema_name=SCHEMA_NAME),
    )
    sale_data = SaleCreate(
        items=[{"producto_id": product_id, "cantidad": 1}],
        es_exenta=True,
    )
    monkeypatch.setattr(commercial_service, "_sync_stock_alerts", lambda **_kw: None)
    monkeypatch.setattr(
        commercial_service,
        "get_sale",
        lambda sale_id, *_args, **_kwargs: {"id": sale_id, "es_exenta": True},
    )

    result = commercial_service.create_sale(sale_data, user, db)

    assert result["es_exenta"] is True
    compiled = [statement.compile().params for statement in db.statements]
    sale_params = next(p for p in compiled if p.get("estado") == "completada")
    assert sale_params["subtotal"] == Decimal("100.00")
    assert sale_params["tasa_impuesto"] == Decimal("12.00")
    assert sale_params["es_exenta"] is True
    assert sale_params["impuesto"] == Decimal("0")
    assert sale_params["total"] == Decimal("100.00")

def test_complete_sale_with_tax_and_discount_flow(monkeypatch):
    """SCRUM-531: Probar flujo Venta + Impuestos verificando subtotal, descuento, impuesto y total."""
    product1_id = uuid4()
    product2_id = uuid4()
    p1 = {
        "id": product1_id,
        "nombre": "Item 1",
        "precio_venta": Decimal("25.50"),
        "stock_actual": Decimal("5"),
        "stock_minimo": Decimal("1"),
        "is_active": True,
    }
    p2 = {
        "id": product2_id,
        "nombre": "Item 2",
        "precio_venta": Decimal("10.00"),
        "stock_actual": Decimal("10"),
        "stock_minimo": Decimal("2"),
        "is_active": True,
    }
    db = FakeDB([[p1, p2], [{"tasa_impuesto": Decimal("12.00")}]] )
    user = SimpleNamespace(
        id=uuid4(),
        company_id=uuid4(),
        company=SimpleNamespace(is_active=True, schema_name=SCHEMA_NAME),
    )
    sale_data = SaleCreate(
        items=[
            {"producto_id": product1_id, "cantidad": 2},
            {"producto_id": product2_id, "cantidad": 1},
        ],
        descuento=Decimal("5.00"),
        es_exenta=False,
    )
    monkeypatch.setattr(commercial_service, "_sync_stock_alerts", lambda **_kw: None)
    monkeypatch.setattr(
        commercial_service,
        "get_sale",
        lambda sale_id, *_args, **_kwargs: {"id": sale_id},
    )

    commercial_service.create_sale(sale_data, user, db)

    assert db.commits == 1
    compiled = [statement.compile().params for statement in db.statements]
    sale_params = next(p for p in compiled if p.get("estado") == "completada")
    assert sale_params["subtotal"] == Decimal("61.00")
    assert sale_params["descuento"] == Decimal("5.00")
    assert sale_params["tasa_impuesto"] == Decimal("12.00")
    assert sale_params["impuesto"] == Decimal("7.32")
    assert sale_params["total"] == Decimal("63.32")
    assert sale_params["es_exenta"] is False