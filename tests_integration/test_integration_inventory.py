"""Integration 2 — Inventory movement: API + inventory service + PostgreSQL.

Components: FastAPI route POST /api/v1/inventory/movements, role guard
(manager), app.services.inventory, SQLAlchemy and the tenant tables producto
and movimiento_inventario in PostgreSQL.
"""
from decimal import Decimal

from sqlalchemy import select

from integration_helpers import MANAGER_EMAIL, auth_headers, product_by_sku


def test_inventory_entry_updates_persisted_stock_and_logs_movement(client, db, tenant_tables):
    headers = auth_headers(client, MANAGER_EMAIL)
    product = product_by_sku(db, tenant_tables, "DEMO-ARROZ")
    stock_before = Decimal(product["stock_actual"])
    db.rollback()  # end the read transaction so the next read sees fresh data

    response = client.post(
        "/api/v1/inventory/movements",
        headers=headers,
        json={
            "producto_id": str(product["id"]),
            "tipo_movimiento": "entrada_compra",
            "cantidad": "5",
            "motivo": "Integration test purchase",
        },
    )

    assert response.status_code == 200, response.text
    movement = response.json()
    assert Decimal(movement["stock_anterior"]) == stock_before
    assert Decimal(movement["stock_resultante"]) == stock_before + 5

    # The API response matches what PostgreSQL actually stored.
    assert Decimal(product_by_sku(db, tenant_tables, "DEMO-ARROZ")["stock_actual"]) == stock_before + 5
    movements = tenant_tables["movimiento_inventario"]
    stored = db.execute(
        select(movements).where(movements.c.id == movement["id"])
    ).mappings().one()
    assert stored["tipo_movimiento"] == "entrada_compra"
    assert Decimal(stored["cantidad"]) == Decimal("5")
    assert str(stored["usuario_id"]) == movement["usuario_id"]


def test_inventory_exit_above_stock_is_rejected_without_changes(client, db, tenant_tables):
    headers = auth_headers(client, MANAGER_EMAIL)
    product = product_by_sku(db, tenant_tables, "DEMO-FRIJOL")
    stock_before = Decimal(product["stock_actual"])
    db.rollback()

    response = client.post(
        "/api/v1/inventory/movements",
        headers=headers,
        json={
            "producto_id": str(product["id"]),
            "tipo_movimiento": "salida_manual",
            "cantidad": str(stock_before + 1),
        },
    )

    assert response.status_code == 400
    assert Decimal(product_by_sku(db, tenant_tables, "DEMO-FRIJOL")["stock_actual"]) == stock_before
