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