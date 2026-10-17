import unittest
from io import BytesIO
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.api.dependencies.auth import get_current_user, get_db
from app.api.v1.routes.reports import router as reports_router
from app.services.reports import (
    ALERT_COLUMNS,
    INVENTORY_COLUMNS,
    MOVEMENT_COLUMNS,
    ReportDataset,
    build_alerts_dataset,
    build_filename,
    build_inventory_dataset,
    build_movements_dataset,
    build_tax_report,
    generate_report,
    list_report_history,
)
from app.services import reports as reports_service
from app.utils.csv_report import escape_formula, render_csv
from app.utils.exceptions import AppError, build_error_payload
from app.utils.pdf_report import render_pdf
from app.utils.xlsx_report import render_xlsx


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

class FiscalDocumentTaxReportTests(unittest.TestCase):
    def _document(self, **overrides):
        document = {
            "id": uuid4(),
            "issue_date": date(2026, 1, 10),
            "document_type": "INVOICE",
            "series": "A",
            "document_number": "100",
            "authorization_number": "AUTH-1",
            "issuer_tax_identifier": "SUP-1",
            "issuer_name": "Supplier",
            "taxable_base": Decimal("400.00"),
            "total": Decimal("448.00"),
            "taxes": [{
                "id": uuid4(), "tax_code": "VAT", "tax_category": "TAXABLE",
                "taxable_base": Decimal("400.00"), "amount": Decimal("48.00"),
            }],
        }
        document.update(overrides)
        
        return document

    def test_general_tax_report_uses_persisted_documents_and_period_result(self):
        sales = [{
            "fecha": date(2026, 1, 12), "subtotal": Decimal("1000"),
            "descuento": Decimal("0"), "impuesto": Decimal("120"),
            "tasa_impuesto": Decimal("0.12"), "total": Decimal("1120"),
            "es_exenta": False, "cliente_nombre": "Customer",
        }]
        debit = {"fiscal_debit": Decimal("120")}
        document = self._document()
        period = {
            "tax_debit": Decimal("120"), "tax_credit": Decimal("48"),
            "net_tax": Decimal("72"), "tax_payable": Decimal("72"),
            "carry_forward": Decimal("0"),
            "details": [{
                "document_id": document["id"], "taxable_base": Decimal("400"),
                "eligible_for_input_credit": True, "tax_amount": Decimal("48"),
            }],
        }
        profile = SimpleNamespace(taxes=[SimpleNamespace(tax_code="VAT")])
        
        with patch.object(reports_service, "_get_fiscal_debit_for_report", return_value=debit), \
             patch.object(reports_service, "_get_input_documents_for_report", return_value=[document]), \
             patch.object(reports_service, "_resolve_report_profile", return_value=profile), \
             patch.object(reports_service.tax_period, "calculate_period", return_value=period):
            report = build_tax_report(
                make_user(), FakeDB([sales, debit]), regime="GENERAL_VAT",
                start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
            )

        purchases, _sales, summary = report.sheets
        self.assertEqual(purchases.rows[0][7], Decimal("400.00"))
        self.assertEqual(purchases.rows[0][8], Decimal("48.00"))
        self.assertEqual(purchases.rows[0][9], Decimal("448.00"))
        self.assertEqual(summary.rows[1][1], Decimal("120.00"))
        self.assertEqual(summary.rows[2][1], Decimal("400.00"))
        self.assertEqual(summary.rows[3][1], Decimal("48.00"))
        self.assertEqual(summary.rows[4][1], Decimal("72.00"))

    def test_purchase_report_preserves_missing_values_and_tax_semantics(self):
        document = self._document(
            taxable_base=None, total=None,
            taxes=[{
                "id": uuid4(), "tax_code": "OTHER_TAX", "tax_category": "EXEMPT",
                "taxable_base": Decimal("0"), "amount": Decimal("0"),
            }],
        )
        profile = SimpleNamespace(taxes=[SimpleNamespace(tax_code="VAT")])
        rows = reports_service._build_tax_purchase_rows([document], "GENERAL_VAT", profile)
        self.assertIsNone(rows[0][7])
        self.assertIsNone(rows[0][8])
        self.assertIsNone(rows[0][9])

    def test_general_purchase_report_reads_line_tax_once(self):
        document = self._document(
            taxes=[{"id": "document-vat", "tax_code": "VAT", "tax_category": "TAXABLE", "amount": Decimal("48.00")}],
            lines=[
                {"taxes": [{"id": "line-vat-1", "tax_code": "VAT", "category": "TAXABLE", "amount": Decimal("18.00")}]},
                {"taxes": [{"id": "line-vat-2", "tax_code": "VAT", "category": "TAXABLE", "amount": Decimal("30.00")}]},
            ],
        )
        profile = SimpleNamespace(taxes=[SimpleNamespace(tax_code="VAT")])

        rows = reports_service._build_tax_purchase_rows([document], "GENERAL_VAT", profile)

        self.assertEqual(rows[0][8], Decimal("48.00"))

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


class ReportGenerationTests(unittest.TestCase):
    def test_renders_csv_and_records_the_generation(self):
        db = FakeDB()

        payload, filename = generate_report(
            make_dataset(), make_user(), db, report_type="inventario", report_format="csv"
        )

        self.assertTrue(payload.startswith(b"\xef\xbb\xbf"))
        self.assertTrue(filename.startswith("reporte_inventario_"))
        self.assertTrue(filename.endswith(".csv"))
        self.assertEqual(db.commits, 1)

    def test_renders_pdf_and_records_the_generation(self):
        db = FakeDB()

        payload, filename = generate_report(
            make_pdf_dataset(), make_user(), db, report_type="alertas", report_format="pdf"
        )

        self.assertTrue(payload.startswith(b"%PDF-"))
        self.assertTrue(filename.endswith(".pdf"))
        self.assertEqual(db.commits, 1)

    def test_the_audit_row_carries_the_type_format_status_and_user(self):
        db = FakeDB()
        user = make_user()

        generate_report(make_dataset(), user, db, report_type="inventario", report_format="csv")

        values = db.statements[0].compile().params
        self.assertEqual(values["tipo"], "inventario")
        self.assertEqual(values["formato"], "csv")
        self.assertEqual(values["estado"], "generado")
        self.assertEqual(values["generado_por_usuario_id"], user.id)
        self.assertIsNone(values["ruta_archivo"])

    def test_the_audit_row_carries_the_period_of_a_ranged_report(self):
        db = FakeDB()
        dataset = make_dataset()
        dataset.metadata = {"periodo_inicio": date(2026, 5, 1), "periodo_fin": date(2026, 5, 31)}

        generate_report(dataset, make_user(), db, report_type="movimientos", report_format="csv")

        values = db.statements[0].compile().params
        self.assertEqual(values["periodo_inicio"], date(2026, 5, 1))
        self.assertEqual(values["periodo_fin"], date(2026, 5, 31))

    def test_rejects_an_unsupported_format(self):
        db = FakeDB()

        with self.assertRaises(AppError) as error:
            generate_report(make_dataset(), make_user(), db, report_type="inventario", report_format="xlsx")

        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(db.commits, 0)

    def test_rolls_back_when_the_audit_row_fails(self):
        class FailingDB(FakeDB):
            def execute(self, statement):
                raise RuntimeError("insert failed")

        db = FailingDB()

        with self.assertRaises(AppError) as error:
            generate_report(make_dataset(), make_user(), db, report_type="inventario", report_format="csv")

        self.assertEqual(error.exception.status_code, 500)
        self.assertEqual(db.rollbacks, 1)

    def test_the_audit_failure_does_not_leak_the_database_error(self):
        leak = 'relation "tenant_xxx.reporte" does not exist'

        class FailingDB(FakeDB):
            def execute(self, statement):
                raise RuntimeError(leak)

        db = FailingDB()

        with self.assertRaises(AppError) as error:
            generate_report(make_dataset(), make_user(), db, report_type="inventario", report_format="csv")

        payload = build_error_payload(error.exception)
        self.assertEqual(payload["message"], "Failed to record report generation")
        self.assertNotIn(leak, payload["message"])
        self.assertNotIn("reporte", payload["message"])

    def test_the_filename_carries_the_type_and_extension(self):
        self.assertTrue(build_filename("movimientos", "pdf").startswith("reporte_movimientos_"))
        self.assertTrue(build_filename("movimientos", "pdf").endswith(".pdf"))


class ReportHistoryTests(unittest.TestCase):
    def test_returns_the_recorded_generations(self):
        recorded = {"id": uuid4(), "tipo": "inventario", "formato": "csv", "estado": "generado"}
        db = FakeDB([[recorded]])

        history = list_report_history(make_user(), db)

        self.assertEqual(history, [recorded])

    def test_applies_the_requested_limit(self):
        db = FakeDB([[]])

        list_report_history(make_user(), db, limit=5)

        self.assertEqual(db.statements[0].compile().params["param_1"], 5)


def make_client(db, role="admin"):
    user = SimpleNamespace(
        id=uuid4(),
        company_id=uuid4(),
        username="fabian",
        is_active=True,
        role=SimpleNamespace(name=role),
        company=SimpleNamespace(is_active=True, schema_name=SCHEMA_NAME, name="Flow Desk SA"),
    )
    app = FastAPI()
    app.include_router(reports_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


class ReportEndpointTests(unittest.TestCase):
    def test_inventory_report_downloads_as_csv_by_default(self):
        db = FakeDB([[make_product_row()]])

        response = make_client(db).get("/api/v1/reports/inventario")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/csv; charset=utf-8")
        self.assertIn("attachment;", response.headers["content-disposition"])
        self.assertIn(".csv", response.headers["content-disposition"])
        self.assertTrue(response.content.startswith(b"\xef\xbb\xbf"))

    def test_inventory_report_downloads_as_pdf_when_requested(self):
        db = FakeDB([[make_product_row()]])

        response = make_client(db).get("/api/v1/reports/inventario?format=pdf")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF-"))

    def test_movements_report_downloads(self):
        db = FakeDB([[make_movement_row()]])

        response = make_client(db).get("/api/v1/reports/movimientos?period=7d")

        self.assertEqual(response.status_code, 200)
        self.assertIn("reporte_movimientos_", response.headers["content-disposition"])

    def test_alerts_report_downloads(self):
        db = FakeDB([[make_alert_row()]])

        response = make_client(db).get("/api/v1/reports/alertas?period=7d&format=pdf")

        self.assertEqual(response.status_code, 200)
        self.assertIn("reporte_alertas_", response.headers["content-disposition"])

    def test_rejects_an_unknown_format_before_touching_the_database(self):
        db = FakeDB([[make_product_row()]])

        response = make_client(db).get("/api/v1/reports/inventario?format=xlsx")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(db.statements, [])

    def test_rejects_a_custom_period_without_both_dates(self):
        db = FakeDB([[make_movement_row()]])

        response = make_client(db).get("/api/v1/reports/movimientos?period=custom&start_date=2026-05-01")

        self.assertEqual(response.status_code, 400)

    def test_history_is_not_shadowed_by_the_report_type_routes(self):
        db = FakeDB([[]])

        response = make_client(db).get("/api/v1/reports/history")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_reports_are_refused_for_a_non_admin_role(self):
        db = FakeDB([[make_product_row()]])

        response = make_client(db, role="employee").get("/api/v1/reports/inventario")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(db.statements, [])

    def test_reports_are_allowed_for_a_superadmin(self):
        db = FakeDB([[make_product_row()]])

        response = make_client(db, role="superadmin").get("/api/v1/reports/inventario")

        self.assertEqual(response.status_code, 200)

    def test_tax_report_returns_a_valid_small_taxpayer_workbook(self):
        sales = [{
            "fecha": datetime(2026, 8, 20, 10, 0),
            "subtotal": Decimal("100.00"),
            "descuento": Decimal("0.00"),
            "impuesto": Decimal("12.00"),
            "tasa_impuesto": Decimal("12.00"),
            "total": Decimal("112.00"),
            "es_exenta": False,
            "cliente_nombre": "Cliente A",
        }]
        debit_rows = [{"subtotal": Decimal("100.00"), "impuesto": Decimal("12.00"), "es_exenta": False}]
        db = FakeDB([sales, debit_rows, []])

        response = make_client(db).get(
            "/api/v1/reports/tributario?regime=SMALL_TAXPAYER&period=custom"
            "&start_date=2026-08-01&end_date=2026-08-31"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertIn("reporte_tributario_", response.headers["content-disposition"])
        workbook = load_workbook(BytesIO(response.content), data_only=True)
        self.assertEqual(workbook.sheetnames, ["Compras", "Ventas", "Resumen"])
        self.assertEqual(list(workbook["Ventas"].values)[0], (
            "No.", "Fecha", "Número Factura", "NIT Comprador", "Nombre Comprador", "Total Venta"
        ))
        self.assertEqual(workbook["Ventas"].cell(2, 5).value, "Cliente A")
        self.assertEqual(workbook["Ventas"].cell(2, 6).value, 112)
        self.assertEqual(workbook["Compras"].max_row, 1)
        self.assertEqual(workbook["Resumen"].cell(3, 2).value, 12)
        self.assertIsNone(workbook["Resumen"].cell(5, 2).value)
        history_params = db.statements[-1].compile().params
        self.assertEqual(history_params["tipo"], "tributario")
        self.assertEqual(history_params["formato"], "xlsx")
        self.assertEqual(history_params["periodo_inicio"], date(2026, 8, 1))
        self.assertEqual(history_params["periodo_fin"], date(2026, 8, 31))

    def test_tax_report_rejects_an_unknown_regime(self):
        db = FakeDB([])

        response = make_client(db).get("/api/v1/reports/tributario?regime=UNKNOWN")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(db.statements, [])

    def test_tax_report_requires_admin_role(self):
        db = FakeDB([])

        response = make_client(db, role="employee").get(
            "/api/v1/reports/tributario?regime=GENERAL_VAT"
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(db.statements, [])

class TaxWorkbookTests(unittest.TestCase):
    def test_general_vat_sales_are_chronological_and_use_numeric_amounts(self):
        rows = [
            {
                "fecha": datetime(2026, 8, 1), "subtotal": Decimal("50.00"),
                "descuento": Decimal("5.00"), "impuesto": Decimal("5.40"),
                "tasa_impuesto": Decimal("12.00"), "total": Decimal("50.40"),
                "es_exenta": False, "cliente_nombre": "Primero",
            },
            {
                "fecha": datetime(2026, 8, 3), "subtotal": Decimal("100.00"),
                "descuento": Decimal("0.00"), "impuesto": Decimal("15.00"),
                "tasa_impuesto": Decimal("15.00"), "total": Decimal("115.00"),
                "es_exenta": False, "cliente_nombre": "Segundo",
            },
        ]
        debit_rows = [
            {"subtotal": row["subtotal"], "impuesto": row["impuesto"], "es_exenta": False}
            for row in rows
        ]
        report = build_tax_report(
            make_user(), FakeDB([rows, debit_rows]), regime="GENERAL_VAT",
            period="custom", start_date=date(2026, 8, 1), end_date=date(2026, 8, 31),
        )

        payload = render_xlsx(report)
        workbook = load_workbook(BytesIO(payload), data_only=True)
        self.assertEqual(report.sheets[1].columns, [
            "No.", "Fecha", "Tipo Documento", "Serie / Autorización", "Número Documento",
            "NIT", "Nombre", "Valor Neto / Base", "IVA", "Total Documento",
        ])
        self.assertEqual(workbook["Ventas"].cell(2, 7).value, "Primero")
        self.assertEqual(workbook["Ventas"].cell(3, 8).value, 100)
        self.assertEqual(workbook["Ventas"].cell(3, 9).value, 15)
        self.assertEqual(workbook["Ventas"].cell(2, 2).value.date(), date(2026, 8, 1))
        self.assertEqual(workbook["Resumen"].cell(3, 2).value, 20.4)
        self.assertIsNone(workbook["Resumen"].cell(4, 2).value)
        self.assertIsNone(workbook["Resumen"].cell(5, 2).value)
        self.assertIsNone(workbook["Resumen"].cell(6, 2).value)
        self.assertEqual(report.sheets[0].rows, [])

    def test_xlsx_renderer_preserves_empty_reports_and_neutralizes_formula_text(self):
        report = ReportDataset(
            title="Prueba / XLSX",
            columns=["Nombre", "Monto"],
            rows=[["=1+1", Decimal("12.34")]],
            metadata={},
        )

        workbook = load_workbook(BytesIO(render_xlsx(report)), data_only=False)

        self.assertEqual(workbook.sheetnames, ["Prueba _ XLSX"])
        self.assertEqual(workbook.active.cell(2, 1).value, "'=1+1")
        self.assertEqual(workbook.active.cell(2, 2).value, 12.34)

    def test_tax_report_has_empty_sales_and_zero_debit_without_data(self):
        report = build_tax_report(
            make_user(), FakeDB([[], []]), regime="SMALL_TAXPAYER",
            period="custom", start_date=date(2026, 8, 1), end_date=date(2026, 8, 31),
        )

        self.assertEqual(report.sheets[1].rows, [])
        self.assertEqual(report.sheets[2].rows[0][1], Decimal("0.00"))
        self.assertIsNone(report.sheets[2].rows[1][1])

if __name__ == "__main__":
    unittest.main()
