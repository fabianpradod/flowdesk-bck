"""Manual inventory movements: which types and data a person may record by hand."""
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import insert, select

from app.schemas.inventory import InventoryMovementCreate
from app.services import inventory as inventory_service
from app.utils.exceptions import AppError
from tests.tenant_sqlite import NOW, new_session, tenant_engine, tenant_user

MANUAL_TYPES = [
    ("entrada_compra", Decimal("13")),
    ("entrada_manual", Decimal("13")),
    ("ajuste_positivo", Decimal("13")),
    ("devolucion_cliente", Decimal("13")),
    ("salida_manual", Decimal("7")),
    ("ajuste_negativo", Decimal("7")),
    ("devolucion_proveedor", Decimal("7")),
]


@pytest.fixture
def tenant():
    engine, tables = tenant_engine()
    return engine, tables, tenant_user()


def insert_product(engine, tables, *, stock="10", minimum="2", active=True):
    product_id = uuid4()
    with new_session(engine) as db:
        db.execute(insert(tables["producto"]).values(
            id=product_id, sku=f"sku-{product_id.hex[:8]}", nombre="Producto", precio_venta=Decimal("5"),
            stock_actual=Decimal(stock), stock_minimo=Decimal(minimum), is_active=active,
            created_at=NOW, updated_at=NOW,
        ))
        db.commit()
    return product_id


def record(engine, user, product_id, tipo, cantidad="3", **extra):
    payload = {"producto_id": product_id, "tipo_movimiento": tipo, "cantidad": Decimal(cantidad), "motivo": "Conteo fisico"}
    payload.update(extra)
    with new_session(engine) as db:
        return inventory_service.create_inventory_movement(InventoryMovementCreate(**payload), user, db)


def stock_of(engine, tables, product_id):
    products = tables["producto"]
    with new_session(engine) as db:
        return db.execute(select(products.c.stock_actual).where(products.c.id == product_id)).scalar_one()


def movements_of(engine, tables, product_id):
    movements = tables["movimiento_inventario"]
    with new_session(engine) as db:
        return db.execute(select(movements).where(movements.c.producto_id == product_id)).mappings().all()


@pytest.mark.parametrize(("tipo", "expected"), MANUAL_TYPES)
def test_manual_types_still_move_stock(tenant, tipo, expected):
    engine, tables, user = tenant
    product_id = insert_product(engine, tables)

    result = record(engine, user, product_id, tipo)

    assert result["stock_resultante"] == expected
    assert stock_of(engine, tables, product_id) == expected


def test_sale_movements_cannot_be_recorded_by_hand(tenant):
    engine, tables, user = tenant
    product_id = insert_product(engine, tables)

    with pytest.raises(AppError) as exc:
        record(engine, user, product_id, "salida_venta")

    assert exc.value.status_code == 400
    assert exc.value.message == "Sale movements are recorded by sales"
    assert stock_of(engine, tables, product_id) == Decimal("10")
    assert movements_of(engine, tables, product_id) == []


@pytest.mark.parametrize("extra", [
    {"referencia_tipo": "venta"},
    {"referencia_id": uuid4()},
    {"referencia_tipo": "anulacion_venta", "referencia_id": uuid4()},
])
def test_manual_movements_cannot_point_at_a_sale_or_void(tenant, extra):
    engine, tables, user = tenant
    product_id = insert_product(engine, tables)

    with pytest.raises(AppError) as exc:
        record(engine, user, product_id, "devolucion_cliente", **extra)

    assert exc.value.status_code == 400
    assert exc.value.message == "References are set by sales and voids"
    assert movements_of(engine, tables, product_id) == []
