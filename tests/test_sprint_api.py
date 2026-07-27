import zipfile
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4
from app.api.dependencies.auth import require_role
from app.models.roles import Role
from app.services.auth import create_employee
from app.services.inventory import ProductImportError, parse_product_import_file
from app.services.inventory import summarize_inventory_metrics
from app.db import init_db
from app.services.inventory import format_inventory_history_row
from app.utils.exceptions import AppError, build_error_payload
import pytest

class QueueQuery:
    def __init__(self, db, model):
        self.db = db
        self.model = model

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def first(self):
        queue = self.db.query_results.setdefault(self.model, [])
        if queue:
            return queue.pop(0)
        return None

    def all(self):
        queue = self.db.query_results.setdefault(self.model, [])
        self.db.query_results[self.model] = []
        return queue

class QueueDB:
    def __init__(self, query_results=None):
        self.query_results = query_results or {}
        self.added = []
        self.commits = 0
        self.refreshed = []

    def query(self, model):
        return QueueQuery(self, model)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        self.refreshed.append(obj)

def build_xlsx_bytes(rows):
    shared_strings = []
    shared_string_indexes = {}

    def shared_index(value):
        text = str(value)
        if text not in shared_string_indexes:
            shared_string_indexes[text] = len(shared_strings)
            shared_strings.append(text)
        return shared_string_indexes[text]

    row_xml = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(row):
            column = chr(ord("A") + column_index)
            cells.append(
                f'<c r="{column}{row_index}" t="s"><v>{shared_index(value)}</v></c>'
            )
        row_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        + "".join(f"<si><t>{value}</t></si>" for value in shared_strings)
        + "</sst>"
    )
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(row_xml)}</sheetData>'
        "</worksheet>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as workbook:
        workbook.writestr("xl/sharedStrings.xml", shared_xml)
        workbook.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buffer.getvalue()

def test_require_role_handles_missing_role_as_forbidden():
    checker = require_role("admin")

    with pytest.raises(AppError) as error:
        checker(SimpleNamespace(role=None))

    assert error.value.status_code == 403
    assert error.value.detail == "Insufficient permissions"

def test_require_role_allows_superadmin_as_elevated():
    checker = require_role("admin")
    user = SimpleNamespace(role=SimpleNamespace(name="superadmin"))

    assert checker(user) is user

def test_create_employee_rejects_superadmin_role():
    db = QueueDB({Role: [SimpleNamespace(id=1, name="superadmin")]})
    data = SimpleNamespace(
        username="new_user",
        email="new@example.com",
        role_id=1,
        company_id=None,
    )
    admin = SimpleNamespace(
        company_id=uuid4(),
        role=SimpleNamespace(name="admin"),
    )

    with pytest.raises(AppError) as error:
        create_employee(data, admin, db)

    assert error.value.status_code == 400
    assert error.value.detail == "Cannot create superadmin users from employees endpoint"
    assert db.added == []

def test_parse_product_import_rejects_invalid_columns():
    content = b"sku,nombre,unexpected\nSKU-1,Arroz,value\n"

    with pytest.raises(ProductImportError) as error:
        parse_product_import_file("products.csv", content)

    assert error.value.code == "invalid_columns"
    assert error.value.status_code == 400
    assert error.value.errors[0]["column"] == "unexpected"

def test_parse_product_import_rejects_duplicate_skus_inside_file():
    content = b"sku,nombre,precio_venta\nSKU-1,Arroz,10.50\nSKU-1,Arroz duplicado,11\n"

    with pytest.raises(ProductImportError) as error:
        parse_product_import_file("products.csv", content)

    assert error.value.code == "invalid_rows"
    assert error.value.errors[0]["code"] == "duplicate_sku"
    assert error.value.errors[0]["row"] == 3

def test_parse_product_import_accepts_xlsx():
    content = build_xlsx_bytes([
        ["sku", "nombre", "precio_venta", "stock_minimo"],
        ["SKU-2", "Frijol", "12.75", "5"],
    ])

    rows = parse_product_import_file("products.xlsx", content)

    assert len(rows) == 1
    assert rows[0]["sku"] == "SKU-2"
    assert rows[0]["precio_venta"] == Decimal("12.75")

def test_inventory_metrics_summary_counts_movements_and_stock_risk():
    products = [
        {"stock_actual": Decimal("0"), "stock_minimo": Decimal("5"), "is_active": True},
        {"stock_actual": Decimal("3"), "stock_minimo": Decimal("5"), "is_active": True},
        {"stock_actual": Decimal("20"), "stock_minimo": Decimal("5"), "is_active": True},
    ]
    movements = [
        {"tipo_movimiento": "entrada_compra", "cantidad": Decimal("15")},
        {"tipo_movimiento": "salida_venta", "cantidad": Decimal("4")},
    ]

    summary = summarize_inventory_metrics(products, movements)

    assert summary["entradas"] == Decimal("15")
    assert summary["salidas"] == Decimal("4")
    assert summary["stock_bajo"] == 1
    assert summary["sin_stock"] == 1

def test_inventory_history_row_is_enriched_with_direction():
    product_id = uuid4()
    movement_id = uuid4()
    now = datetime.now(timezone.utc)

    row = format_inventory_history_row(
        {
            "id": movement_id,
            "producto_id": product_id,
            "sku": "SKU-1",
            "nombre": "Arroz",
            "tipo_movimiento": "salida_venta",
            "fecha": now,
            "cantidad": Decimal("2"),
            "stock_resultante": Decimal("8"),
            "motivo": "venta",
        }
    )

    assert row["id"] == movement_id
    assert row["producto_id"] == product_id
    assert row["direction"] == "out"
    assert row["sku"] == "SKU-1"

def test_app_error_exposes_uniform_payload():
    error = AppError(status_code=400, message="Bad request", code="bad_request")

    assert build_error_payload(error) == {
        "message": "Bad request",
        "code": "bad_request",
        "errors": [],
    }

def test_demo_seed_is_skipped_when_disabled():
    engine = Mock()
    connection_context = MagicMock()
    engine.connect.return_value = connection_context
    connection = engine.connect.return_value.__enter__.return_value
    session = Mock()

    with (
        patch.object(init_db, "get_engine", return_value=engine),
        patch.object(init_db, "SessionLocal", return_value=session),
        patch.object(init_db.Base.metadata, "create_all"),
        patch.object(init_db, "seed_roles"),
        patch.object(init_db, "seed_superadmin"),
        patch.object(init_db, "seed_demo_data") as seed_demo_mock,
        patch.object(init_db, "DEMO_SEED_ENABLED", False),
    ):
        init_db.init_db()

    connection.execute.assert_called()
    seed_demo_mock.assert_not_called()
    session.close.assert_called_once()