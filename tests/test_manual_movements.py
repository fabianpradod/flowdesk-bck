"""Manual inventory movements: which types and data a person may record by hand."""
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.schemas.inventory import InventoryMovementCreate
from app.services import inventory as inventory_service
from app.utils.exceptions import AppError
from tests.tenant_sqlite import insert_product, new_session, tenant_engine, tenant_user

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


@pytest.mark.parametrize("tipo", ["ajuste_positivo", "ajuste_negativo"])
@pytest.mark.parametrize("motivo", [None, "", "   "])
def test_adjustments_need_a_reason(tipo, motivo):
    with pytest.raises(ValidationError) as exc:
        InventoryMovementCreate(producto_id=uuid4(), tipo_movimiento=tipo, cantidad=Decimal("1"), motivo=motivo)

    assert "motivo is required for adjustments" in str(exc.value)


def test_other_manual_movements_keep_the_reason_optional():
    movement = InventoryMovementCreate(producto_id=uuid4(), tipo_movimiento="entrada_manual", cantidad=Decimal("1"))

    assert movement.motivo is None


def test_adjustment_without_reason_answers_422_over_http(admin_client):
    response = admin_client.post(
        "/api/v1/inventory/movements",
        json={"producto_id": str(uuid4()), "tipo_movimiento": "ajuste_negativo", "cantidad": "1"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
