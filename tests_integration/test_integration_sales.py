"""Integration 3 — Sale: commercial service + inventory + tax config + PostgreSQL.

Components: FastAPI routes PUT /api/v1/commercial/tax-configuration,
POST /api/v1/commercial/sales and GET /api/v1/commercial/sales/{id},
app.services.commercial, SQLAlchemy and the tenant tables
configuracion_tributaria, venta, detalle_venta, producto and
movimiento_inventario in PostgreSQL (including row locks and advisory locks).
"""
from decimal import Decimal

from sqlalchemy import select

from integration_helpers import ADMIN_EMAIL, auth_headers, product_by_sku


def test_sale_persists_totals_items_and_discounts_stock(client, db, tenant_tables):
    headers = auth_headers(client, ADMIN_EMAIL)

    tax = client.put(
        "/api/v1/commercial/tax-configuration",
        headers=headers,
        json={"tasa_impuesto": "12"},
    )
    assert tax.status_code == 200, tax.text

    product = product_by_sku(db, tenant_tables, "DEMO-ARROZ")
    stock_before = Decimal(product["stock_actual"])
    price = Decimal(product["precio_venta"])  
    db.rollback()

    response = client.post(
        "/api/v1/commercial/sales",
        headers=headers,
        json={"items": [{"producto_id": str(product["id"]), "cantidad": "2"}]},
    )

    assert response.status_code == 201, response.text
    sale = response.json()
    expected_subtotal = price * 2                                     # 37.00
    expected_tax = (expected_subtotal * Decimal("0.12")).quantize(Decimal("0.01"))  # 4.44
    assert sale["consumidor_final"] is True
    assert Decimal(sale["subtotal"]) == expected_subtotal
    assert Decimal(sale["tasa_impuesto"]) == Decimal("12")
    assert Decimal(sale["impuesto"]) == expected_tax
    assert Decimal(sale["total"]) == expected_subtotal + expected_tax
    assert len(sale["items"]) == 1

    sales = tenant_tables["venta"]
    stored_sale = db.execute(select(sales).where(sales.c.id == sale["id"])).mappings().one()
    assert Decimal(stored_sale["total"]) == Decimal(sale["total"])
    assert stored_sale["estado"] == "completada"

    lines = tenant_tables["detalle_venta"]
    stored_lines = db.execute(
        select(lines).where(lines.c.venta_id == sale["id"])
    ).mappings().all()
    assert [Decimal(line["cantidad"]) for line in stored_lines] == [Decimal("2")]

    assert Decimal(product_by_sku(db, tenant_tables, "DEMO-ARROZ")["stock_actual"]) == stock_before - 2

    movements = tenant_tables["movimiento_inventario"]
    movement = db.execute(
        select(movements).where(movements.c.referencia_id == sale["id"])
    ).mappings().one()
    assert movement["tipo_movimiento"] == "salida_venta"
    assert Decimal(movement["stock_resultante"]) == stock_before - 2

    detail = client.get(f"/api/v1/commercial/sales/{sale['id']}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert Decimal(detail.json()["total"]) == Decimal(sale["total"])


def test_sale_with_insufficient_stock_rolls_back_everything(client, db, tenant_tables):
    headers = auth_headers(client, ADMIN_EMAIL)
    product = product_by_sku(db, tenant_tables, "DEMO-CAFE")
    stock_before = Decimal(product["stock_actual"])
    sales = tenant_tables["venta"]
    sales_before = len(db.execute(select(sales.c.id)).all())
    db.rollback()

    response = client.post(
        "/api/v1/commercial/sales",
        headers=headers,
        json={"items": [{"producto_id": str(product["id"]), "cantidad": str(stock_before + 1)}]},
    )

    assert response.status_code == 400
    assert Decimal(product_by_sku(db, tenant_tables, "DEMO-CAFE")["stock_actual"]) == stock_before
    assert len(db.execute(select(sales.c.id)).all()) == sales_before
