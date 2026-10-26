"""What an inactive product still allows: corrections yes, new business no."""
from decimal import Decimal

import pytest
from sqlalchemy import select, update

from app.schemas.commercial import SaleCreate, SaleItemCreate, SaleVoid
from app.schemas.inventory import InventoryMovementCreate
from app.services import commercial as commercial_service
from app.services import inventory as inventory_service
from app.utils.exceptions import AppError
from tests.tenant_sqlite import insert_product, new_session, tenant_engine, tenant_user

BLOCKED_TYPES = ["entrada_compra", "entrada_manual", "devolucion_cliente", "salida_manual", "devolucion_proveedor"]


@pytest.fixture
def tenant():
    engine, tables = tenant_engine()
    return engine, tables, tenant_user()


def deactivate(engine, tables, product_id):
    products = tables["producto"]
    with new_session(engine) as db:
        db.execute(update(products).where(products.c.id == product_id).values(is_active=False))
        db.commit()


def stock_of(engine, tables, product_id):
    products = tables["producto"]
    with new_session(engine) as db:
        return db.execute(select(products.c.stock_actual).where(products.c.id == product_id)).scalar_one()


def record(engine, user, product_id, tipo):
    with new_session(engine) as db:
        return inventory_service.create_inventory_movement(
            InventoryMovementCreate(producto_id=product_id, tipo_movimiento=tipo, cantidad=Decimal("2"), motivo="Conteo"),
            user,
            db,
        )


def sell(engine, user, product_id):
    with new_session(engine) as db:
        return commercial_service.create_sale(
            SaleCreate(items=[SaleItemCreate(producto_id=product_id, cantidad=Decimal("3"))]), user, db,
        )


def test_inactive_products_cannot_be_sold(tenant):
    engine, tables, user = tenant
    product_id = insert_product(engine, tables, active=False)

    with pytest.raises(AppError) as exc:
        sell(engine, user, product_id)

    assert exc.value.status_code == 400
    assert exc.value.message.startswith("Product is inactive")


@pytest.mark.parametrize("tipo", BLOCKED_TYPES)
def test_inactive_products_refuse_ordinary_manual_movements(tenant, tipo):
    engine, tables, user = tenant
    product_id = insert_product(engine, tables, active=False)

    with pytest.raises(AppError) as exc:
        record(engine, user, product_id, tipo)

    assert exc.value.status_code == 400
    assert exc.value.message == "Product is inactive"
    assert stock_of(engine, tables, product_id) == Decimal("10")


@pytest.mark.parametrize(("tipo", "expected"), [("ajuste_positivo", Decimal("12")), ("ajuste_negativo", Decimal("8"))])
def test_inactive_products_accept_adjustments(tenant, tipo, expected):
    # Writing off what is left after deactivating a product is a correction.
    engine, tables, user = tenant
    product_id = insert_product(engine, tables, active=False)

    result = record(engine, user, product_id, tipo)

    assert result["stock_resultante"] == expected
    assert stock_of(engine, tables, product_id) == expected


def test_sale_of_a_product_deactivated_later_can_still_be_voided(tenant):
    engine, tables, user = tenant
    product_id = insert_product(engine, tables, stock="10")
    sale = sell(engine, user, product_id)
    deactivate(engine, tables, product_id)

    with new_session(engine) as db:
        result = commercial_service.void_sale(sale["id"], SaleVoid(motivo="Devuelto"), user, db)

    assert result["estado"] == "anulada"
    assert stock_of(engine, tables, product_id) == Decimal("10")
