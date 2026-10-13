import importlib.util
import random
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

SEED_PATH = Path(__file__).parent / "load" / "seed_load_data.py"
spec = importlib.util.spec_from_file_location("seed_load_data", SEED_PATH)
seed_load_data = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed_load_data)

NOW = datetime(2026, 10, 12, 12, 0, 0)
SMALL = {"suppliers": 5, "products": 40, "clients": 12, "movements": 300, "sales": 60, "alerts": 6, "tasks_per_user": 3}


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql+psycopg2://postgres@db.example.com:5432/flowdesk",
        "postgresql+psycopg2://admin:secret@10.0.0.5/flowdesk",
        "postgresql+psycopg2:///flowdesk",
    ],
)
def test_refuses_non_local_database(dsn):
    with pytest.raises(SystemExit):
        seed_load_data.require_local_dsn(dsn)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_accepts_local_database(host):
    dsn = f"postgresql+psycopg2://postgres@{host}:55432/flowdesk_perf"
    assert seed_load_data.require_local_dsn(dsn) == dsn


def build_rows():
    user_ids = [uuid4() for _ in range(4)]
    return seed_load_data.build_tenant_rows(random.Random(7), NOW, user_ids, SMALL), user_ids


def test_builds_requested_volume():
    rows, user_ids = build_rows()

    assert len(rows["proveedor"]) == SMALL["suppliers"]
    assert len(rows["producto"]) == SMALL["products"]
    assert len(rows["proveedor_producto"]) == 2 * SMALL["products"]
    assert len(rows["cliente"]) == SMALL["clients"]
    assert len(rows["movimiento_inventario"]) == SMALL["movements"]
    assert len(rows["venta"]) == SMALL["sales"]
    assert len(rows["alerta"]) == SMALL["alerts"]
    assert len(rows["tarea"]) == SMALL["tasks_per_user"] * len(user_ids)


def test_rows_reference_their_own_tenant():
    rows, user_ids = build_rows()
    product_ids = {row["id"] for row in rows["producto"]}
    supplier_ids = {row["id"] for row in rows["proveedor"]}
    client_ids = {row["id"] for row in rows["cliente"]}
    sale_ids = {row["id"] for row in rows["venta"]}

    assert {row["proveedor_id"] for row in rows["producto"]} <= supplier_ids
    assert {row["producto_id"] for row in rows["movimiento_inventario"]} <= product_ids
    assert {row["producto_id"] for row in rows["detalle_venta"]} <= product_ids
    assert {row["venta_id"] for row in rows["detalle_venta"]} == sale_ids
    assert {row["cliente_id"] for row in rows["venta"]} - {None} <= client_ids
    assert {row["usuario_id"] for row in rows["venta"]} <= set(user_ids)


def test_sale_totals_match_their_lines():
    rows, _ = build_rows()
    lines_by_sale = {}
    for line in rows["detalle_venta"]:
        assert line["subtotal"] == line["cantidad"] * line["precio_unitario"]
        lines_by_sale.setdefault(line["venta_id"], Decimal("0"))
        lines_by_sale[line["venta_id"]] += line["subtotal"]

    for sale in rows["venta"]:
        assert sale["subtotal"] == lines_by_sale[sale["id"]]
        assert sale["total"] == sale["subtotal"] + sale["impuesto"]


def test_dates_cover_the_last_year():
    rows, _ = build_rows()
    dates = [row["fecha"] for row in rows["movimiento_inventario"] + rows["venta"]]

    assert min(dates) >= NOW - timedelta(days=365)
    assert max(dates) <= NOW
    assert any(date >= NOW - timedelta(days=30) for date in dates)


def test_movements_keep_stock_non_negative():
    rows, _ = build_rows()

    for movement in rows["movimiento_inventario"]:
        assert movement["cantidad"] > 0
        assert movement["stock_anterior"] >= 0
        assert movement["stock_resultante"] >= 0
