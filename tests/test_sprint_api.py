import unittest
import zipfile
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4


class SprintApiTests(unittest.TestCase):
    def test_require_role_handles_missing_role_as_forbidden(self):
        from app.api.dependencies.auth import require_role
        from app.utils.exceptions import AppError

        checker = require_role("admin")

        with self.assertRaises(AppError) as error:
            checker(SimpleNamespace(role=None))

        self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(error.exception.detail, "Insufficient permissions")

    def test_require_role_allows_superadmin_as_elevated(self):
        from app.api.dependencies.auth import require_role

        checker = require_role("admin")
        user = SimpleNamespace(role=SimpleNamespace(name="superadmin"))

        self.assertIs(checker(user), user)

    def test_create_employee_rejects_superadmin_role(self):
        from app.models.roles import Role
        from app.services.auth import create_employee
        from app.utils.exceptions import AppError

        db = QueueDB({Role: [SimpleNamespace(id=1, name="superadmin")]})
        data = SimpleNamespace(
            username="new_user",
            email="new@example.com",
            role_id=1,
            company_id=None,
        )
        admin = SimpleNamespace(company_id=uuid4())

        with self.assertRaises(AppError) as error:
            create_employee(data, admin, db)

        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(error.exception.detail, "Cannot create superadmin users from employees endpoint")
        self.assertEqual(db.added, [])

    def test_parse_product_import_rejects_invalid_columns(self):
        from app.services.inventory import ProductImportError, parse_product_import_file

        content = b"sku,nombre,unexpected\nSKU-1,Arroz,value\n"

        with self.assertRaises(ProductImportError) as error:
            parse_product_import_file("products.csv", content)

        self.assertEqual(error.exception.code, "invalid_columns")
        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(error.exception.errors[0]["column"], "unexpected")

    def test_parse_product_import_rejects_duplicate_skus_inside_file(self):
        from app.services.inventory import ProductImportError, parse_product_import_file

        content = b"sku,nombre,precio_venta\nSKU-1,Arroz,10.50\nSKU-1,Arroz duplicado,11\n"

        with self.assertRaises(ProductImportError) as error:
            parse_product_import_file("products.csv", content)

        self.assertEqual(error.exception.code, "invalid_rows")
        self.assertEqual(error.exception.errors[0]["code"], "duplicate_sku")
        self.assertEqual(error.exception.errors[0]["row"], 3)

    def test_parse_product_import_accepts_xlsx(self):
        from app.services.inventory import parse_product_import_file

        content = build_xlsx_bytes([
            ["sku", "nombre", "precio_venta", "stock_minimo"],
            ["SKU-2", "Frijol", "12.75", "5"],
        ])

        rows = parse_product_import_file("products.xlsx", content)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sku"], "SKU-2")
        self.assertEqual(rows[0]["precio_venta"], Decimal("12.75"))

    def test_inventory_metrics_summary_counts_movements_and_stock_risk(self):
        from app.services.inventory import summarize_inventory_metrics

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

        self.assertEqual(summary["entradas"], Decimal("15"))
        self.assertEqual(summary["salidas"], Decimal("4"))
        self.assertEqual(summary["stock_bajo"], 1)
        self.assertEqual(summary["sin_stock"], 1)

    def test_inventory_history_row_is_enriched_with_direction(self):
        from app.services.inventory import format_inventory_history_row

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

        self.assertEqual(row["id"], movement_id)
        self.assertEqual(row["producto_id"], product_id)
        self.assertEqual(row["direction"], "out")
        self.assertEqual(row["sku"], "SKU-1")

    def test_app_error_exposes_uniform_payload(self):
        from app.utils.exceptions import AppError, build_error_payload

        error = AppError(status_code=400, message="Bad request", code="bad_request")

        self.assertEqual(
            build_error_payload(error),
            {"message": "Bad request", "code": "bad_request", "errors": []},
        )

    def test_demo_seed_is_skipped_when_disabled(self):
        from app.db import init_db

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
            cells.append(f'<c r="{column}{row_index}" t="s"><v>{shared_index(value)}</v></c>')
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


if __name__ == "__main__":
    unittest.main()
