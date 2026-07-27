from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
import pytest
from app.services import inventory as inventory_service
from app.tenancy.runtime import get_tenant_tables
from app.utils.exceptions import AppError

class FakeResult:
    def __init__(self, rows):
        self.rows = rows or []

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def one(self):
        if not self.rows:
            raise LookupError("No rows returned")
        if len(self.rows) != 1:
            raise LookupError(f"Expected 1 row, got {len(self.rows)}")
        return self.rows[0]

    def all(self):
        return list(self.rows)

def _statement_values(statement):
    raw_values = getattr(statement, "_values", None)
    if raw_values:
        values = {}
        for key, value in raw_values.items():
            key_name = getattr(key, "key", None) or getattr(key, "name", None) or str(key)
            values[key_name] = getattr(value, "value", value)
        return values

    try:
        return dict(statement.compile().params)
    except Exception:
        return {}

class InMemoryInventoryDB:
    def __init__(self, product_rows=None):
        self.tables = {
            "producto": list(product_rows or []),
            "movimiento_inventario": [],
            "alerta": [],
        }
        self.commits = 0
        self.rollbacks = 0

    def execute(self, statement):
        stmt_type = type(statement).__name__

        table = getattr(statement, "table", None)
        if table is None and hasattr(statement, "get_final_froms"):
            froms = statement.get_final_froms()
            table = froms[0] if froms else None

        table_name = getattr(table, "name", None)

        if stmt_type == "Select":
            rows = self.tables.get(table_name, [])
            if not rows:
                return FakeResult([])
            if table_name == "movimiento_inventario":
                return FakeResult([rows[-1]])
            return FakeResult([rows[0]])

        if stmt_type == "Update":
            values = _statement_values(statement)
            rows = self.tables.get(table_name, [])
            if rows and table_name == "producto":
                rows[0].update(values)
            return FakeResult([])

        if stmt_type == "Insert":
            values = _statement_values(statement)
            self.tables.setdefault(table_name, []).append(dict(values))
            return FakeResult([])

        raise NotImplementedError(f"Unsupported statement type: {stmt_type}")

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

@pytest.fixture(autouse=True)
def patch_inventory_helpers(monkeypatch):
    tenant_tables = get_tenant_tables("tenant_test")

    monkeypatch.setattr(
        inventory_service,
        "_get_tenant_tables_for_user",
        lambda _user: tenant_tables,
    )
    monkeypatch.setattr(
        inventory_service,
        "_sync_stock_alerts",
        lambda **kwargs: None,
    )

def make_product_row(
    *,
    product_id=None,
    stock_actual=Decimal("10"),
    stock_minimo=Decimal("5"),
    is_active=True,
):
    now = datetime.now(timezone.utc)
    return {
        "id": product_id or uuid4(),
        "proveedor_id": uuid4(),
        "sku": "SKU-1",
        "nombre": "Arroz",
        "descripcion": "Producto demo",
        "precio_venta": Decimal("10.00"),
        "stock_actual": Decimal(str(stock_actual)),
        "stock_minimo": Decimal(str(stock_minimo)),
        "unidad_medida": "unidad",
        "is_active": is_active,
        "created_at": now,
        "updated_at": now,
    }

def make_user():
    return SimpleNamespace(
        id=uuid4(),
        company_id=uuid4(),
        company=SimpleNamespace(
            is_active=True,
            schema_name="tenant_test",
        ),
        role=SimpleNamespace(name="admin"),
    )

def test_inventory_movement_success():
    product_id = uuid4()
    db = InMemoryInventoryDB([make_product_row(product_id=product_id, stock_actual=Decimal("10"))])
    current_user = make_user()

    data = SimpleNamespace(
        producto_id=product_id,
        tipo_movimiento="salida_venta",
        cantidad=Decimal("3"),
        motivo="venta",
        referencia_tipo=None,
        referencia_id=None,
    )

    result = inventory_service.create_inventory_movement(data, current_user, db)

    assert result["producto_id"] == product_id
    assert result["cantidad"] == Decimal("3")
    assert result["stock_anterior"] == Decimal("10")
    assert result["stock_resultante"] == Decimal("7")
    assert db.commits == 1
    assert db.rollbacks == 0

def test_inventory_product_not_found():
    db = InMemoryInventoryDB([])
    current_user = make_user()

    data = SimpleNamespace(
        producto_id=uuid4(),
        tipo_movimiento="salida_venta",
        cantidad=Decimal("1"),
        motivo=None,
        referencia_tipo=None,
        referencia_id=None,
    )

    with pytest.raises(AppError) as error:
        inventory_service.create_inventory_movement(data, current_user, db)

    assert error.value.status_code == 404
    assert "Product not found" in str(error.value.detail)

def test_inactive_product_cannot_move():
    product_id = uuid4()
    db = InMemoryInventoryDB([make_product_row(product_id=product_id, is_active=False)])
    current_user = make_user()

    data = SimpleNamespace(
        producto_id=product_id,
        tipo_movimiento="salida_venta",
        cantidad=Decimal("1"),
        motivo=None,
        referencia_tipo=None,
        referencia_id=None,
    )

    with pytest.raises(AppError) as error:
        inventory_service.create_inventory_movement(data, current_user, db)

    assert error.value.status_code == 400
    assert "inactive" in str(error.value.detail).lower()

def test_invalid_inventory_quantity_negative():
    product_id = uuid4()
    db = InMemoryInventoryDB([make_product_row(product_id=product_id)])
    current_user = make_user()

    data = SimpleNamespace(
        producto_id=product_id,
        tipo_movimiento="salida_venta",
        cantidad=Decimal("-5"),
        motivo=None,
        referencia_tipo=None,
        referencia_id=None,
    )

    with pytest.raises(AppError) as error:
        inventory_service.create_inventory_movement(data, current_user, db)

    assert error.value.status_code == 400
    assert "greater than zero" in str(error.value.detail).lower()

def test_excessive_quantity_is_rejected():
    product_id = uuid4()
    db = InMemoryInventoryDB([make_product_row(product_id=product_id, stock_actual=Decimal("1"))])
    current_user = make_user()

    data = SimpleNamespace(
        producto_id=product_id,
        tipo_movimiento="salida_venta",
        cantidad=Decimal("999999999999999"),
        motivo=None,
        referencia_tipo=None,
        referencia_id=None,
    )

    with pytest.raises(AppError) as error:
        inventory_service.create_inventory_movement(data, current_user, db)

    assert error.value.status_code == 400
    assert "quantity exceeds maximum allowed value" in str(error.value.detail).lower()

def test_unsupported_movement_type():
    product_id = uuid4()
    db = InMemoryInventoryDB([make_product_row(product_id=product_id)])
    current_user = make_user()

    data = SimpleNamespace(
        producto_id=product_id,
        tipo_movimiento="OUT",
        cantidad=Decimal("1"),
        motivo=None,
        referencia_tipo=None,
        referencia_id=None,
    )

    with pytest.raises(AppError) as error:
        inventory_service.create_inventory_movement(data, current_user, db)

    assert error.value.status_code == 400
    assert "unsupported inventory movement type" in str(error.value.detail).lower()