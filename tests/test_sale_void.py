"""Voiding a sale: mandatory reason, stock back, history kept."""
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import insert, select

from app.schemas.commercial import SaleCreate, SaleItemCreate, SaleResponse, SaleVoid
from app.services import commercial as commercial_service
from app.utils.exceptions import AppError
from tests.tenant_sqlite import NOW, insert_product, new_session, tenant_engine, tenant_user


@pytest.fixture
def tenant():
    engine, tables = tenant_engine()
    return engine, tables, tenant_user()


def sell(engine, user, *lines):
    with new_session(engine) as db:
        return commercial_service.create_sale(
            SaleCreate(items=[SaleItemCreate(producto_id=product_id, cantidad=Decimal(qty)) for product_id, qty in lines]),
            user,
            db,
        )


def void(engine, user, sale_id, motivo="Error de digitacion"):
    with new_session(engine) as db:
        return commercial_service.void_sale(sale_id, SaleVoid(motivo=motivo), user, db)


def stock_of(engine, tables, product_id):
    products = tables["producto"]
    with new_session(engine) as db:
        return db.execute(select(products.c.stock_actual).where(products.c.id == product_id)).scalar_one()


def test_void_puts_stock_back_and_records_reason_author_and_time(tenant):
    engine, tables, user = tenant
    first = insert_product(engine, tables, stock="10")
    second = insert_product(engine, tables, stock="4")
    sale = sell(engine, user, (first, "3"), (second, "1.5"))
    assert stock_of(engine, tables, first) == Decimal("7")

    result = void(engine, user, sale["id"], motivo="  Cliente pago con tarjeta rechazada  ")

    assert result["estado"] == "anulada"
    assert result["motivo_anulacion"] == "Cliente pago con tarjeta rechazada"
    assert result["anulada_por"] == user.id
    assert result["anulada_en"] is not None
    assert stock_of(engine, tables, first) == Decimal("10")
    assert stock_of(engine, tables, second) == Decimal("4")
    # The amounts and items stay as they were sold.
    assert result["total"] == sale["total"]
    assert [item["cantidad"] for item in result["items"]] == [item["cantidad"] for item in sale["items"]]
    SaleResponse.model_validate(result)


def test_sale_detail_shows_the_void(tenant):
    engine, tables, user = tenant
    sale = sell(engine, user, (insert_product(engine, tables), "1"))
    void(engine, user, sale["id"], motivo="Duplicada")

    with new_session(engine) as db:
        detail = commercial_service.get_sale(sale["id"], user, db)

    assert detail["estado"] == "anulada"
    assert detail["motivo_anulacion"] == "Duplicada"


def test_completed_sales_carry_no_void_data(tenant):
    engine, tables, user = tenant

    sale = sell(engine, user, (insert_product(engine, tables), "1"))

    assert (sale["motivo_anulacion"], sale["anulada_por"], sale["anulada_en"]) == (None, None, None)


@pytest.mark.parametrize("motivo", ["", "   ", "x" * 201])
def test_reason_is_mandatory_and_bounded(motivo):
    with pytest.raises(ValidationError):
        SaleVoid(motivo=motivo)


def test_reason_cannot_be_left_out():
    with pytest.raises(ValidationError):
        SaleVoid()


def test_unknown_sale_answers_404(tenant):
    engine, _tables, user = tenant

    with pytest.raises(AppError) as exc:
        void(engine, user, uuid4())

    assert exc.value.status_code == 404
    assert exc.value.message == "Sale not found"


def test_only_completed_sales_can_be_voided(tenant):
    engine, tables, user = tenant
    sale_id = uuid4()
    with new_session(engine) as db:
        db.execute(insert(tables["venta"]).values(
            id=sale_id, usuario_id=user.id, fecha=NOW, estado="borrador", created_at=NOW, updated_at=NOW,
        ))
        db.commit()

    with pytest.raises(AppError) as exc:
        void(engine, user, sale_id)

    assert exc.value.status_code == 400
    assert exc.value.message == "Only completed sales can be voided"
