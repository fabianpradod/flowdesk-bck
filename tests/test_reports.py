import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.services.reports import (
    ALERT_COLUMNS,
    INVENTORY_COLUMNS,
    MOVEMENT_COLUMNS,
    ReportDataset,
    build_alerts_dataset,
    build_inventory_dataset,
    build_movements_dataset,
)
from app.utils.csv_report import escape_formula, render_csv
from app.utils.exceptions import AppError
from app.utils.pdf_report import render_pdf


SCHEMA_NAME = "tenant_" + "a" * 32


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def one(self):
        return self.rows[0]

    def __iter__(self):
        return iter(self.rows)


class FakeDB:
    """Returns the queued row batches in order, one per execute() call."""

    def __init__(self, results=None):
        self.results = list(results or [])
        self.statements = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, statement):
        self.statements.append(statement)
        rows = self.results.pop(0) if self.results else []
        return FakeResult(rows)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def make_user():
    company = SimpleNamespace(is_active=True, schema_name=SCHEMA_NAME, name="Flow Desk SA")
    return SimpleNamespace(id=uuid4(), company_id=uuid4(), username="fabian", company=company)


def make_product_row(**overrides):
    row = {
        "sku": "trn-001",
        "nombre": "Tornillo",
        "proveedor": "Acme",
        "stock_actual": Decimal("3"),
        "stock_minimo": Decimal("10"),
        "precio_venta": Decimal("2.5"),
        "unidad_medida": "unidad",
        "is_active": True,
    }
    row.update(overrides)
    return row


def make_movement_row(**overrides):
    row = {
        "id": uuid4(),
        "producto_id": uuid4(),
        "sku": "trn-001",
        "nombre": "Tornillo",
        "tipo_movimiento": "salida_venta",
        "fecha": datetime(2026, 8, 19, 14, 32, tzinfo=timezone.utc),
        "cantidad": Decimal("5"),
        "stock_resultante": Decimal("3"),
        "motivo": None,
    }
    row.update(overrides)
    return row


def make_alert_row(**overrides):
    row = {
        "fecha": datetime(2026, 8, 19, 14, 32, tzinfo=timezone.utc),
        "sku": "trn-001",
        "nombre": "Tornillo",
        "tipo": "stock_bajo",
        "mensaje": "El producto alcanzó stock bajo",
        "estado": "pendiente",
        "resuelta_en": None,
    }
    row.update(overrides)
    return row


def where_text(statement):
    return str(statement.whereclause) if statement.whereclause is not None else ""


class InventoryDatasetTests(unittest.TestCase):
    def test_uses_the_spanish_column_headers(self):
        db = FakeDB([[make_product_row()]])

        dataset = build_inventory_dataset(make_user(), db)

        self.assertEqual(dataset.title, "Reporte de Inventario")
        self.assertEqual(dataset.columns, INVENTORY_COLUMNS)

    def test_formats_decimals_to_two_places_and_maps_the_status(self):
        db = FakeDB([[make_product_row(is_active=False)]])

        dataset = build_inventory_dataset(make_user(), db)

        self.assertEqual(
            dataset.rows[0],
            ["trn-001", "Tornillo", "Acme", "3.00", "10.00", "2.50", "unidad", "Inactivo"],
        )

    def test_renders_a_missing_supplier_as_an_empty_cell(self):
        db = FakeDB([[make_product_row(proveedor=None)]])

        dataset = build_inventory_dataset(make_user(), db)

        self.assertEqual(dataset.rows[0][2], "—")

    def test_only_low_stock_compares_stock_against_the_minimum(self):
        db = FakeDB([[make_product_row()]])

        build_inventory_dataset(make_user(), db, only_low_stock=True)

        self.assertIn("stock_actual <=", where_text(db.statements[0]))

    def test_filters_by_product_and_status_when_requested(self):
        db = FakeDB([[make_product_row()]])
        product_id = uuid4()

        build_inventory_dataset(make_user(), db, product_id=product_id, is_active=True)

        clause = where_text(db.statements[0])
        self.assertIn("producto.id", clause)
        self.assertIn("is_active", clause)

    def test_sends_no_filters_when_none_are_requested(self):
        db = FakeDB([[make_product_row()]])

        dataset = build_inventory_dataset(make_user(), db)

        self.assertEqual(where_text(db.statements[0]), "")
        self.assertEqual(dataset.metadata["filtros"], "Producto: todos · Estado: todos · Solo stock bajo: no")

    def test_returns_an_empty_row_list_when_nothing_matches(self):
        db = FakeDB([[]])

        dataset = build_inventory_dataset(make_user(), db)

        self.assertEqual(dataset.rows, [])
        self.assertEqual(dataset.columns, INVENTORY_COLUMNS)


class MovementsDatasetTests(unittest.TestCase):
    def test_labels_the_movement_type_and_direction_in_spanish(self):
        db = FakeDB([[make_movement_row()]])

        dataset = build_movements_dataset(make_user(), db, period="7d")

        self.assertEqual(dataset.columns, MOVEMENT_COLUMNS)
        self.assertEqual(dataset.rows[0][3], "Salida por venta")
        self.assertEqual(dataset.rows[0][4], "Salida")

    def test_labels_inbound_movements_as_entrada(self):
        db = FakeDB([[make_movement_row(tipo_movimiento="entrada_compra")]])

        dataset = build_movements_dataset(make_user(), db, period="7d")

        self.assertEqual(dataset.rows[0][3], "Entrada por compra")
        self.assertEqual(dataset.rows[0][4], "Entrada")

    def test_formats_the_timestamp_to_the_minute(self):
        db = FakeDB([[make_movement_row()]])

        dataset = build_movements_dataset(make_user(), db, period="7d")

        self.assertEqual(dataset.rows[0][0], "2026-08-19 14:32")

    def test_restricts_the_query_to_the_resolved_period(self):
        db = FakeDB([[make_movement_row()]])

        dataset = build_movements_dataset(
            make_user(),
            db,
            period="custom",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 31),
        )

        self.assertEqual(dataset.metadata["periodo_inicio"], date(2026, 5, 1))
        self.assertEqual(dataset.metadata["periodo_fin"], date(2026, 5, 31))
        self.assertIn("Periodo: 2026-05-01 a 2026-05-31", dataset.metadata["filtros"])

    def test_rejects_a_custom_period_without_both_dates(self):
        db = FakeDB([[make_movement_row()]])

        with self.assertRaises(AppError) as error:
            build_movements_dataset(make_user(), db, period="custom", start_date=date(2026, 5, 1))

        self.assertEqual(error.exception.status_code, 400)

    def test_filters_by_product_and_movement_type(self):
        db = FakeDB([[make_movement_row()]])

        dataset = build_movements_dataset(
            make_user(), db, period="7d", product_id=uuid4(), movement_type="salida_venta"
        )

        clause = where_text(db.statements[0])
        self.assertIn("producto_id", clause)
        self.assertIn("tipo_movimiento", clause)
        self.assertIn("Tipo: Salida por venta", dataset.metadata["filtros"])


class AlertsDatasetTests(unittest.TestCase):
    def test_humanizes_the_alert_type_and_status(self):
        db = FakeDB([[make_alert_row()]])

        dataset = build_alerts_dataset(make_user(), db, period="7d")

        self.assertEqual(dataset.columns, ALERT_COLUMNS)
        self.assertEqual(dataset.rows[0][3], "Stock bajo")
        self.assertEqual(dataset.rows[0][5], "Pendiente")

    def test_renders_an_unresolved_alert_with_an_empty_resolution_cell(self):
        db = FakeDB([[make_alert_row()]])

        dataset = build_alerts_dataset(make_user(), db, period="7d")

        self.assertEqual(dataset.rows[0][6], "—")

    def test_open_only_restricts_the_query_to_pending_alerts(self):
        db = FakeDB([[make_alert_row()]])

        dataset = build_alerts_dataset(make_user(), db, period="7d", open_only=True)

        self.assertIn("pendiente", db.statements[0].compile().params.values())
        self.assertIn("Solo abiertas: sí", dataset.metadata["filtros"])

    def test_open_only_disabled_keeps_resolved_alerts(self):
        db = FakeDB([[make_alert_row(estado="resuelta", resuelta_en=datetime(2026, 8, 20, 9, 0))]])

        dataset = build_alerts_dataset(make_user(), db, period="7d", open_only=False)

        self.assertNotIn("pendiente", db.statements[0].compile().params.values())
        self.assertEqual(dataset.rows[0][5], "Resuelta")
        self.assertEqual(dataset.rows[0][6], "2026-08-20 09:00")


def make_dataset(columns=None, rows=None):
    return ReportDataset(
        title="Reporte de Inventario",
        columns=columns if columns is not None else ["SKU", "Stock Mínimo"],
        rows=rows if rows is not None else [["trn-001", "10.00"]],
        metadata={},
    )


class CsvRenderTests(unittest.TestCase):
    def test_starts_with_a_bom_so_excel_reads_the_accents(self):
        payload = render_csv(make_dataset())

        self.assertTrue(payload.startswith(b"\xef\xbb\xbf"))
        self.assertTrue(payload.decode("utf-8-sig").startswith("SKU"))

    def test_round_trips_spanish_accents(self):
        payload = render_csv(make_dataset(columns=["Stock Mínimo", "Dirección"]))

        self.assertIn("Stock Mínimo", payload.decode("utf-8-sig"))
        self.assertIn("Dirección", payload.decode("utf-8-sig"))

    def test_writes_the_header_row_followed_by_the_data_rows(self):
        payload = render_csv(make_dataset(rows=[["a", "1.00"], ["b", "2.00"]]))

        lines = payload.decode("utf-8-sig").strip().splitlines()
        self.assertEqual(lines, ["SKU,Stock Mínimo", "a,1.00", "b,2.00"])

    def test_renders_a_header_only_file_when_there_are_no_rows(self):
        payload = render_csv(make_dataset(rows=[]))

        self.assertEqual(payload.decode("utf-8-sig").strip(), "SKU,Stock Mínimo")

    def test_quotes_cells_containing_the_delimiter(self):
        payload = render_csv(make_dataset(rows=[["a,b", "1.00"]]))

        self.assertIn('"a,b"', payload.decode("utf-8-sig"))


class CsvFormulaEscapingTests(unittest.TestCase):
    def test_escapes_a_leading_equals(self):
        self.assertEqual(escape_formula("=SUM(A1)"), "'=SUM(A1)")

    def test_escapes_every_formula_prefix(self):
        for value in ("=cmd", "+cmd", "@cmd", "\tcmd", "\rcmd"):
            with self.subTest(value=value):
                self.assertEqual(escape_formula(value), f"'{value}")

    def test_escapes_a_payload_disguised_as_a_negative_number(self):
        self.assertEqual(escape_formula("-5+cmd|' /C calc'!A0"), "'-5+cmd|' /C calc'!A0")

    def test_leaves_a_genuine_negative_number_numeric(self):
        self.assertEqual(escape_formula("-5.00"), "-5.00")

    def test_escapes_non_finite_values(self):
        self.assertEqual(escape_formula("-Infinity"), "'-Infinity")

    def test_leaves_ordinary_text_untouched(self):
        self.assertEqual(escape_formula("Tornillo"), "Tornillo")

    def test_escaping_survives_the_full_render(self):
        payload = render_csv(make_dataset(rows=[["=SUM(A1)", "1.00"]]))

        self.assertIn("'=SUM(A1)", payload.decode("utf-8-sig"))


PDF_METADATA = {
    "empresa": "Flow Desk SA",
    "generado_por": "fabian",
    "fecha_generacion": datetime(2026, 8, 20, 14, 32, tzinfo=timezone.utc),
    "filtros": "Periodo: 2026-07-21 a 2026-08-20 · Producto: todos",
}


def make_pdf_dataset(rows=None):
    return ReportDataset(
        title="Reporte de Inventario",
        columns=INVENTORY_COLUMNS,
        rows=rows if rows is not None else [
            ["trn-001", "Tornillo", "Acme", "3.00", "10.00", "2.50", "unidad", "Activo"]
        ],
        metadata=dict(PDF_METADATA),
    )


def page_count(payload: bytes) -> int:
    return payload.count(b"/Type /Page\n") + payload.count(b"/Type /Page/")


class PdfRenderTests(unittest.TestCase):
    def test_returns_a_pdf_payload(self):
        payload = render_pdf(make_pdf_dataset())

        self.assertTrue(payload.startswith(b"%PDF-"))
        self.assertTrue(payload.rstrip().endswith(b"%%EOF"))

    def test_renders_a_single_page_for_a_short_report(self):
        self.assertEqual(page_count(render_pdf(make_pdf_dataset())), 1)

    def test_paginates_a_long_report(self):
        rows = [
            [f"trn-{index:03d}", "Tornillo", "Acme", "1.00", "2.00", "3.00", "unidad", "Activo"]
            for index in range(200)
        ]

        payload = render_pdf(make_pdf_dataset(rows))

        self.assertGreater(page_count(payload), 1)

    def test_renders_a_placeholder_page_when_there_are_no_rows(self):
        payload = render_pdf(make_pdf_dataset([]))

        self.assertTrue(payload.startswith(b"%PDF-"))
        self.assertEqual(page_count(payload), 1)

    def test_survives_markup_characters_in_the_data(self):
        rows = [["<b>trn</b>", "Acme & Co", "a<b", "1.00", "2.00", "3.00", "unidad", "Activo"]]

        payload = render_pdf(make_pdf_dataset(rows))

        self.assertTrue(payload.startswith(b"%PDF-"))

    def test_survives_accented_headers_and_cells(self):
        rows = [["trn-001", "Atornillación", "Acme", "1.00", "2.00", "3.00", "unidad", "Activo"]]

        payload = render_pdf(make_pdf_dataset(rows))

        self.assertTrue(payload.startswith(b"%PDF-"))

    def test_renders_without_optional_metadata(self):
        dataset = make_pdf_dataset()
        dataset.metadata = {}

        payload = render_pdf(dataset)

        self.assertTrue(payload.startswith(b"%PDF-"))


class ReportMetadataTests(unittest.TestCase):
    def test_carries_the_company_and_the_generating_user(self):
        db = FakeDB([[make_product_row()]])

        dataset = build_inventory_dataset(make_user(), db)

        self.assertEqual(dataset.metadata["empresa"], "Flow Desk SA")
        self.assertEqual(dataset.metadata["generado_por"], "fabian")
        self.assertIsInstance(dataset.metadata["fecha_generacion"], datetime)

    def test_falls_back_to_the_email_when_the_username_is_missing(self):
        user = make_user()
        user.username = None
        user.email = "fabian@example.com"
        db = FakeDB([[make_product_row()]])

        dataset = build_inventory_dataset(user, db)

        self.assertEqual(dataset.metadata["generado_por"], "fabian@example.com")

    def test_inventory_reports_carry_no_period(self):
        db = FakeDB([[make_product_row()]])

        dataset = build_inventory_dataset(make_user(), db)

        self.assertIsNone(dataset.metadata["periodo_inicio"])
        self.assertIsNone(dataset.metadata["periodo_fin"])


if __name__ == "__main__":
    unittest.main()
