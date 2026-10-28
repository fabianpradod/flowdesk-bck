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


def movements_of(engine, tables, product_id):
    movements = tables["movimiento_inventario"]
    with new_session(engine) as db:
        return db.execute(
            select(movements).where(movements.c.producto_id == product_id).order_by(movements.c.tipo_movimiento)
        ).mappings().all()


def alerts_of(engine, tables, product_id):
    alerts = tables["alerta"]
    with new_session(engine) as db:
        return db.execute(select(alerts.c.tipo, alerts.c.estado).where(alerts.c.producto_id == product_id)).all()


def sale_row(engine, tables, sale_id):
    sales = tables["venta"]
    with new_session(engine) as db:
        return db.execute(select(sales).where(sales.c.id == sale_id)).mappings().one()


def test_each_line_gets_a_reversal_movement_pointing_at_the_sale(tenant):
    engine, tables, user = tenant
    product_id = insert_product(engine, tables, stock="10")
    sale = sell(engine, user, (product_id, "4"))

    void(engine, user, sale["id"], motivo="Precio mal cargado")

    reversal, original = movements_of(engine, tables, product_id)
    assert original["tipo_movimiento"] == "salida_venta"
    assert (original["referencia_tipo"], original["referencia_id"]) == ("venta", sale["id"])
    assert (original["stock_anterior"], original["stock_resultante"]) == (Decimal("10"), Decimal("6"))
    assert reversal["tipo_movimiento"] == "devolucion_cliente"
    assert (reversal["referencia_tipo"], reversal["referencia_id"]) == ("anulacion_venta", sale["id"])
    assert reversal["cantidad"] == Decimal("4")
    assert (reversal["stock_anterior"], reversal["stock_resultante"]) == (Decimal("6"), Decimal("10"))
    assert reversal["motivo"] == "Precio mal cargado"
    assert reversal["usuario_id"] == user.id


def test_reversal_starts_from_the_current_stock_not_the_one_at_sale_time(tenant):
    engine, tables, user = tenant
    product_id = insert_product(engine, tables, stock="10")
    sale = sell(engine, user, (product_id, "4"))
    sell(engine, user, (product_id, "5"))

    void(engine, user, sale["id"])

    assert stock_of(engine, tables, product_id) == Decimal("5")


@pytest.mark.parametrize(("sold", "alert"), [("2", "stock_bajo"), ("3", "sin_stock")])
def test_low_stock_alerts_raised_by_the_sale_are_resolved(tenant, sold, alert):
    engine, tables, user = tenant
    product_id = insert_product(engine, tables, stock="3", minimum="2")
    sale = sell(engine, user, (product_id, sold))
    assert alerts_of(engine, tables, product_id) == [(alert, "pendiente")]

    void(engine, user, sale["id"])

    assert alerts_of(engine, tables, product_id) == [(alert, "resuelta")]


def test_second_void_answers_400_and_returns_stock_once(tenant):
    engine, tables, user = tenant
    product_id = insert_product(engine, tables, stock="10")
    sale = sell(engine, user, (product_id, "4"))
    void(engine, user, sale["id"])

    with pytest.raises(AppError) as exc:
        void(engine, user, sale["id"], motivo="Otra vez")

    assert exc.value.status_code == 400
    assert exc.value.message == "Sale is already voided"
    assert stock_of(engine, tables, product_id) == Decimal("10")
    assert len(movements_of(engine, tables, product_id)) == 2
    assert sale_row(engine, tables, sale["id"])["motivo_anulacion"] == "Error de digitacion"


def test_void_that_read_the_sale_before_another_void_committed_changes_nothing(tenant, monkeypatch):
    engine, tables, user = tenant
    product_id = insert_product(engine, tables, stock="10")
    sale = sell(engine, user, (product_id, "4"))
    void(engine, user, sale["id"])
    # The late request read the sale while it was still completed.
    monkeypatch.setattr(commercial_service, "_fetch_sale_state", lambda *_args: {"id": sale["id"], "estado": "completada"})

    with pytest.raises(AppError) as exc:
        void(engine, user, sale["id"], motivo="Tarde")

    assert exc.value.status_code == 400
    assert stock_of(engine, tables, product_id) == Decimal("10")
    assert len(movements_of(engine, tables, product_id)) == 2
    assert sale_row(engine, tables, sale["id"])["motivo_anulacion"] == "Error de digitacion"


def test_failure_halfway_leaves_the_sale_and_stock_untouched(tenant, monkeypatch):
    engine, tables, user = tenant
    first = insert_product(engine, tables, stock="10")
    second = insert_product(engine, tables, stock="10")
    sale = sell(engine, user, (first, "4"), (second, "2"))
    calls = []

    def fail_on_second_line(**kwargs):
        calls.append(kwargs["product_id"])
        if len(calls) == 2:
            raise RuntimeError("alert table unavailable")

    monkeypatch.setattr(commercial_service, "_sync_stock_alerts", fail_on_second_line)

    with pytest.raises(AppError) as exc:
        void(engine, user, sale["id"])

    assert exc.value.status_code == 500
    assert exc.value.message == "Sale void failed"
    row = sale_row(engine, tables, sale["id"])
    assert (row["estado"], row["motivo_anulacion"], row["anulada_por"]) == ("completada", None, None)
    assert stock_of(engine, tables, first) == Decimal("6")
    assert stock_of(engine, tables, second) == Decimal("8")
    assert [m["tipo_movimiento"] for m in movements_of(engine, tables, first)] == ["salida_venta"]


def test_voided_sales_stay_in_the_client_history(tenant):
    engine, tables, user = tenant
    client_id = uuid4()
    with new_session(engine) as db:
        db.execute(insert(tables["cliente"]).values(id=client_id, nombre="Ana", is_active=True, created_at=NOW, updated_at=NOW))
        db.commit()
    with new_session(engine) as db:
        sale = commercial_service.create_sale(
            SaleCreate(cliente_id=client_id, items=[SaleItemCreate(producto_id=insert_product(engine, tables), cantidad=Decimal("1"))]),
            user,
            db,
        )
    void(engine, user, sale["id"], motivo="Cliente equivocado")

    with new_session(engine) as db:
        history = commercial_service.list_client_purchases(client_id, user, db)

    assert [(entry["id"], entry["estado"], entry["motivo_anulacion"]) for entry in history] == [
        (sale["id"], "anulada", "Cliente equivocado"),
    ]


def test_voided_sales_are_left_out_of_sales_metrics():
    from app.services.analytics import FINAL_SALE_STATES

    assert commercial_service.VOIDED_SALE_STATE not in FINAL_SALE_STATES
    assert commercial_service.COMPLETED_SALE_STATE in FINAL_SALE_STATES
