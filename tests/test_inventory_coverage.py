import io
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4
import pytest
from app.services import inventory
from app.utils.exceptions import AppError, ProductImportError

def test_validate_csv_injection_accepts_safe_values():
    errors = []
    inventory._validate_csv_injection("normal value", 2, "nombre", errors)
    assert errors == []

@pytest.mark.parametrize("value", ["=SUM(A1)", "+cmd", "-formula", "@cmd"])
def test_validate_csv_injection_rejects_formula_prefixes(value):
    errors = []
    inventory._validate_csv_injection(value, 3, "sku", errors)
    assert len(errors) == 1
    assert errors[0]["code"] == "csv_injection"

def test_validate_import_size_accepts_limit():
    inventory._validate_import_size([{"sku": str(i)} for i in range(inventory.MAX_IMPORT_ROWS)])

def test_validate_import_size_rejects_too_many_rows():
    with pytest.raises(ProductImportError) as exc:
        inventory._validate_import_size([{}] * (inventory.MAX_IMPORT_ROWS + 1))
    assert exc.value.code == "import_too_large"

def test_parse_csv_utf8_bom_and_normalizes_rows():
    content = "\ufeffsku,nombre,descripcion,precio_venta,stock_minimo,unidad_medida\n SKU-1 , Producto , Desc , 12.50 , 3 , caja\n".encode()
    rows = inventory.parse_product_import_file("products.csv", content)

    assert rows == [{
        "sku": "SKU-1",
        "nombre": "Producto",
        "descripcion": "Desc",
        "precio_venta": Decimal("12.50"),
        "stock_minimo": Decimal("3"),
        "unidad_medida": "caja",
        "proveedor_id": None,
    }]

def test_parse_csv_invalid_utf8_is_rejected():
    with pytest.raises(ProductImportError) as exc:
        inventory.parse_product_import_file("products.csv", b"\xff\xfe")
    assert exc.value.code == "invalid_format"

def test_parse_csv_without_headers_is_rejected():
    with pytest.raises(ProductImportError) as exc:
        inventory.parse_product_import_file("products.csv", b"")
    assert exc.value.code == "empty_file"

def test_parse_import_rejects_unsupported_extension():
    with pytest.raises(ProductImportError) as exc:
        inventory.parse_product_import_file("products.txt", b"sku,nombre\nA,Product")
    assert exc.value.code == "unsupported_format"

def test_normalize_import_rejects_missing_and_unexpected_columns():
    with pytest.raises(ProductImportError) as exc:
        inventory._normalize_product_import_rows([
            {"sku": "A", "nombre": "Product", "not_allowed": "x"}
        ])

    assert exc.value.code == "invalid_columns"
    codes = {error["code"] for error in exc.value.errors}
    assert "unexpected_column" in codes

def test_normalize_import_rejects_missing_required_column():
    with pytest.raises(ProductImportError) as exc:
        inventory._normalize_product_import_rows([{"sku": "A"}])

    assert exc.value.code == "invalid_columns"
    assert any(error["code"] == "missing_column" for error in exc.value.errors)

def test_normalize_import_skips_blank_rows():
    rows = inventory._normalize_product_import_rows([
        {"sku": "A", "nombre": "Product"},
        {"sku": " ", "nombre": " "},
    ])
    assert len(rows) == 1
    assert rows[0]["sku"] == "A"

def test_normalize_import_rejects_duplicate_sku():
    with pytest.raises(ProductImportError) as exc:
        inventory._normalize_product_import_rows([
            {"sku": "A", "nombre": "First"},
            {"sku": "A", "nombre": "Second"},
        ])
    assert any(error["code"] == "duplicate_sku" for error in exc.value.errors)

def test_normalize_import_rejects_empty_product_data():
    with pytest.raises(ProductImportError) as exc:
        inventory._normalize_product_import_rows([
            {"sku": "", "nombre": ""},
        ])

    assert exc.value.status_code == 400
    assert exc.value.detail == "Import file is empty"

def test_normalize_import_rejects_invalid_decimal_and_negative_decimal():
    with pytest.raises(ProductImportError) as exc:
        inventory._normalize_product_import_rows([
            {
                "sku": "A",
                "nombre": "Product",
                "precio_venta": "abc",
                "stock_minimo": "-1",
            }
        ])

    codes = {error["code"] for error in exc.value.errors}
    assert "invalid_decimal" in codes
    assert "negative_decimal" in codes

def test_normalize_import_rejects_invalid_supplier_uuid():
    with pytest.raises(ProductImportError) as exc:
        inventory._normalize_product_import_rows([
            {
                "sku": "A",
                "nombre": "Product",
                "proveedor_id": "not-a-uuid",
            }
        ])

    assert any(error["code"] == "invalid_uuid" for error in exc.value.errors)

def test_normalize_import_accepts_valid_supplier_uuid():
    supplier_id = uuid4()
    rows = inventory._normalize_product_import_rows([
        {
            "sku": "A",
            "nombre": "Product",
            "descripcion": " Description ",
            "precio_venta": "10",
            "stock_minimo": "",
            "unidad_medida": "",
            "proveedor_id": str(supplier_id),
        }
    ])

    assert rows[0]["proveedor_id"] == supplier_id
    assert rows[0]["descripcion"] == "Description"
    assert rows[0]["stock_minimo"] == Decimal("0")
    assert rows[0]["unidad_medida"] == "unidad"

def test_clean_text_helpers():
    assert inventory._clean_text(None) == ""
    assert inventory._clean_text("  abc  ") == "abc"
    assert inventory._clean_optional_text("   ") is None
    assert inventory._clean_optional_text(" abc ") == "abc"
    assert inventory._normalize_header(None) == ""
    assert inventory._normalize_header(" SKU ") == "sku"

def test_parse_decimal_empty_defaults_to_zero():
    errors = []
    assert inventory._parse_nonnegative_decimal("", "precio_venta", 2, errors) == Decimal("0")
    assert errors == []

def test_parse_decimal_invalid_records_error():
    errors = []
    result = inventory._parse_nonnegative_decimal("abc", "precio_venta", 2, errors)
    assert result == Decimal("0")
    assert errors[0]["code"] == "invalid_decimal"

def test_parse_decimal_negative_records_error():
    errors = []
    result = inventory._parse_nonnegative_decimal("-5", "precio_venta", 2, errors)
    assert result == Decimal("0")
    assert errors[0]["code"] == "negative_decimal"

def test_parse_optional_uuid_empty_returns_none():
    errors = []
    assert inventory._parse_optional_uuid(" ", "proveedor_id", 2, errors) is None
    assert errors == []

def test_parse_optional_uuid_invalid_records_error():
    errors = []
    assert inventory._parse_optional_uuid("bad", "proveedor_id", 2, errors) is None
    assert errors[0]["code"] == "invalid_uuid"

def test_xlsx_column_index_handles_normal_and_invalid_references():
    assert inventory._xlsx_column_index("A1") == 0
    assert inventory._xlsx_column_index("Z1") == 25
    assert inventory._xlsx_column_index("AA1") == 26
    assert inventory._xlsx_column_index("BC99") == 54
    assert inventory._xlsx_column_index("123") == 0

def test_xlsx_cell_value_supports_inline_string_number_and_shared_string():
    namespace = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    inline = inventory.ElementTree.fromstring(
        '<c xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" t="inlineStr">'
        '<is><t>Hello</t></is></c>'
    )
    numeric = inventory.ElementTree.fromstring(
        '<c xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><v>42</v></c>'
    )
    shared = inventory.ElementTree.fromstring(
        '<c xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" t="s"><v>0</v></c>'
    )
    bad_shared = inventory.ElementTree.fromstring(
        '<c xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" t="s"><v>bad</v></c>'
    )
    missing = inventory.ElementTree.fromstring(
        '<c xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><v/></c>'
    )

    assert inventory._read_xlsx_cell_value(inline, [], namespace) == "Hello"
    assert inventory._read_xlsx_cell_value(numeric, [], namespace) == "42"
    assert inventory._read_xlsx_cell_value(shared, ["Shared"], namespace) == "Shared"
    assert inventory._read_xlsx_cell_value(bad_shared, ["Shared"], namespace) == ""
    assert inventory._read_xlsx_cell_value(missing, [], namespace) == ""

def _xlsx_bytes(rows_xml: str, shared_xml: str | None = None) -> bytes:
    files = {
        "xl/worksheets/sheet1.xml": (
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<sheetData>{rows_xml}</sheetData></worksheet>"
        ).encode()
    }
    if shared_xml is not None:
        files["xl/sharedStrings.xml"] = shared_xml.encode()

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as workbook:
        for name, value in files.items():
            workbook.writestr(name, value)
    return output.getvalue()

def test_read_xlsx_rows_reads_headers_and_skips_blank_rows():
    rows_xml = """
    <row r="1">
      <c r="A1" t="inlineStr"><is><t>sku</t></is></c>
      <c r="B1" t="inlineStr"><is><t>nombre</t></is></c>
    </row>
    <row r="2">
      <c r="A2" t="inlineStr"><is><t>SKU-1</t></is></c>
      <c r="B2" t="inlineStr"><is><t>Producto</t></is></c>
    </row>
    <row r="3">
      <c r="A3" t="inlineStr"><is><t> </t></is></c>
      <c r="B3" t="inlineStr"><is><t> </t></is></c>
    </row>
    """
    rows = inventory._read_xlsx_rows(_xlsx_bytes(rows_xml))
    assert rows == [{"sku": "SKU-1", "nombre": "Producto"}]

def test_read_xlsx_rows_supports_shared_strings():
    shared_xml = """
    <sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
      <si><t>sku</t></si>
      <si><t>nombre</t></si>
      <si><t>SKU-1</t></si>
      <si><t>Producto</t></si>
    </sst>
    """
    rows_xml = """
    <row>
      <c r="A1" t="s"><v>0</v></c>
      <c r="B1" t="s"><v>1</v></c>
    </row>
    <row>
      <c r="A2" t="s"><v>2</v></c>
      <c r="B2" t="s"><v>3</v></c>
    </row>
    """
    rows = inventory._read_xlsx_rows(_xlsx_bytes(rows_xml, shared_xml))
    assert rows == [{"sku": "SKU-1", "nombre": "Producto"}]

def test_read_xlsx_rejects_invalid_zip():
    with pytest.raises(ProductImportError) as exc:
        inventory._read_xlsx_rows(b"not-a-zip")
    assert exc.value.code == "invalid_format"

def test_read_xlsx_rejects_invalid_xml():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as workbook:
        workbook.writestr("xl/worksheets/sheet1.xml", b"<invalid")
    with pytest.raises(ProductImportError) as exc:
        inventory._read_xlsx_rows(output.getvalue())
    assert exc.value.code == "invalid_format"

def test_read_xlsx_returns_empty_when_sheet_has_no_rows():
    assert inventory._read_xlsx_rows(
        _xlsx_bytes("<row></row>")
    ) == []

def test_shared_strings_missing_file_returns_empty():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as workbook:
        workbook.writestr("other.txt", "x")
    with zipfile.ZipFile(io.BytesIO(output.getvalue())) as workbook:
        assert inventory._read_xlsx_shared_strings(workbook) == []

def test_shared_strings_invalid_xml_returns_empty():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as workbook:
        workbook.writestr("xl/sharedStrings.xml", b"<invalid")
    with zipfile.ZipFile(io.BytesIO(output.getvalue())) as workbook:
        assert inventory._read_xlsx_shared_strings(workbook) == []

def test_resolve_analytics_range_supports_ytd_and_fixed_periods():
    now = datetime(2026, 8, 9, 15, 30, tzinfo=timezone.utc)

    ytd = inventory._resolve_analytics_range("ytd", None, None, now=now)
    seven_days = inventory._resolve_analytics_range("7d", None, None, now=now)

    assert ytd["start"] == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert ytd["end"] == now
    assert seven_days["end"] == now
    assert (seven_days["end"] - seven_days["start"]).days == 7

def test_resolve_analytics_range_supports_custom_period():
    result = inventory._resolve_analytics_range(
        "custom",
        date(2026, 5, 1),
        date(2026, 5, 31),
    )
    assert result["start"] == datetime(2026, 5, 1, tzinfo=timezone.utc)
    assert result["end"].date() == date(2026, 5, 31)

def test_resolve_analytics_range_rejects_reversed_dates():
    with pytest.raises(AppError) as exc:
        inventory._resolve_analytics_range(
            "custom",
            date(2026, 6, 1),
            date(2026, 5, 1),
        )
    assert exc.value.status_code == 400

def test_aggregate_without_previous_does_not_add_delta_fields():
    product_id = uuid4()
    rows = [{
        "fecha": datetime(2026, 5, 6, tzinfo=timezone.utc),
        "cantidad": Decimal("5"),
        "stock_resultante": Decimal("10"),
        "tipo_movimiento": "entrada_manual",
        "producto_id": product_id,
        "sku": "A",
        "nombre": "A",
    }]
    points = inventory._aggregate_movement_rows(rows, window="day", include_previous=False)
    assert points[0]["inbound_quantity"] == Decimal("5")
    assert "previous_net_quantity" not in points[0]

def test_aggregate_previous_zero_produces_no_percentage():
    product_id = uuid4()
    rows = [
        {
            "fecha": datetime(2026, 5, 1, tzinfo=timezone.utc),
            "cantidad": Decimal("5"),
            "stock_resultante": Decimal("5"),
            "tipo_movimiento": "entrada_manual",
            "producto_id": product_id,
            "sku": "A",
            "nombre": "A",
        },
        {
            "fecha": datetime(2026, 5, 2, tzinfo=timezone.utc),
            "cantidad": Decimal("3"),
            "stock_resultante": Decimal("2"),
            "tipo_movimiento": "salida_venta",
            "producto_id": product_id,
            "sku": "A",
            "nombre": "A",
        },
    ]
    points = inventory._aggregate_movement_rows(rows, window="day", include_previous=True)
    assert points[0]["previous_net_quantity"] is None
    assert points[1]["previous_net_quantity"] == Decimal("5")
    assert points[1]["net_change_percent"] == Decimal("-160.00")

def test_aggregate_handles_inbound_and_outbound_movements():
    product_id = uuid4()
    rows = [
        {
            "fecha": datetime(2026, 5, 1, tzinfo=timezone.utc),
            "cantidad": Decimal("10"),
            "stock_resultante": Decimal("10"),
            "tipo_movimiento": "entrada_compra",
        },
        {
            "fecha": datetime(2026, 5, 1, 1, tzinfo=timezone.utc),
            "cantidad": Decimal("4"),
            "stock_resultante": Decimal("6"),
            "tipo_movimiento": "salida_venta",
        },
    ]
    points = inventory._aggregate_movement_rows(rows, window="day", include_previous=False)
    assert points[0]["inbound_quantity"] == Decimal("10")
    assert points[0]["outbound_quantity"] == Decimal("4")
    assert points[0]["net_quantity"] == Decimal("6")
    assert points[0]["movement_count"] == 2
    assert points[0]["ending_stock"] == Decimal("6")

@pytest.mark.parametrize("sort_by", ["outbound", "inbound", "net", "movement_count", "stock_risk"],)
def test_product_sort_key_supports_all_modes(sort_by):
    product = {
        "outbound_quantity": Decimal("3"),
        "inbound_quantity": Decimal("8"),
        "net_quantity": Decimal("5"),
        "movement_count": 4,
        "stock_risk_score": Decimal("20"),
    }
    key = inventory._product_sort_key(product, sort_by)
    assert isinstance(key, tuple)

def test_rank_product_rows_applies_limit_and_groups_movements():
    first = uuid4()
    second = uuid4()
    rows = [
        {
            "producto_id": first, "sku": "A", "nombre": "A",
            "cantidad": Decimal("10"), "stock_actual": Decimal("4"),
            "stock_minimo": Decimal("5"), "stock_resultante": Decimal("4"),
            "tipo_movimiento": "salida_venta",
        },
        {
            "producto_id": first, "sku": "A", "nombre": "A",
            "cantidad": Decimal("2"), "stock_actual": Decimal("2"),
            "stock_minimo": Decimal("5"), "stock_resultante": Decimal("2"),
            "tipo_movimiento": "entrada_manual",
        },
        {
            "producto_id": second, "sku": "B", "nombre": "B",
            "cantidad": Decimal("1"), "stock_actual": Decimal("10"),
            "stock_minimo": Decimal("5"), "stock_resultante": Decimal("10"),
            "tipo_movimiento": "entrada_manual",
        },
    ]
    ranked = inventory._rank_product_rows(rows, sort_by="movement_count", limit=1)
    assert len(ranked) == 1
    assert ranked[0]["product_id"] == first
    assert ranked[0]["movement_count"] == 2

def test_stock_risk_score_handles_zero_minimum_and_zero_demand():
    assert inventory._stock_risk_score(
        Decimal("0"), Decimal("0"), Decimal("10")
    ) == Decimal("0")

    score = inventory._stock_risk_score(
        Decimal("10"), Decimal("20"), Decimal("0")
    )
    assert score == Decimal("35.00")

@pytest.mark.parametrize(("movement_type", "expected"),
    [
        ("entrada_compra", "in"),
        ("entrada_manual", "in"),
        ("ajuste_positivo", "in"),
        ("devolucion_cliente", "in"),
        ("salida_venta", "out"),
        ("salida_manual", "out"),
        ("ajuste_negativo", "out"),
        ("devolucion_proveedor", "out"),
    ],
)
def test_movement_direction_supports_all_types(movement_type, expected):
    assert inventory._movement_direction(movement_type) == expected

def test_movement_direction_rejects_unknown_type():
    with pytest.raises(AppError) as exc:
        inventory._movement_direction("unknown")
    assert exc.value.status_code == 400

@pytest.mark.parametrize(("window", "expected_start", "expected_label"),
    [
        ("day", date(2026, 5, 6), "2026-05-06"),
        ("week", date(2026, 5, 4), "2026-05-04 week"),
        ("month", date(2026, 5, 1), "2026-05"),
    ],
)
def test_bucket_helpers_support_day_week_and_month(window, expected_start, expected_label):
    value = datetime(2026, 5, 6, 12, tzinfo=timezone.utc)
    start = inventory._bucket_start(value, window)
    assert start == expected_start
    assert inventory._bucket_label(start, window) == expected_label

def test_empty_bucket_has_expected_defaults():
    bucket = inventory._empty_bucket(date(2026, 5, 1), "month")
    assert bucket["period_label"] == "2026-05"
    assert bucket["inbound_quantity"] == Decimal("0")
    assert bucket["outbound_quantity"] == Decimal("0")
    assert bucket["net_quantity"] == Decimal("0")
    assert bucket["movement_count"] == 0
    assert bucket["ending_stock"] is None

def test_date_to_datetime_supports_start_and_end_of_day():
    value = date(2026, 5, 6)
    assert inventory._date_to_datetime(value) == datetime(
        2026, 5, 6, 0, 0, tzinfo=timezone.utc
    )
    assert inventory._date_to_datetime(value, end_of_day=True).hour == 23
    assert inventory._date_to_datetime(value, end_of_day=True).minute == 59
    assert inventory._date_to_datetime(value, end_of_day=True).second == 59

def test_to_decimal_supports_decimal_and_numeric_values():
    value = Decimal("12.50")
    assert inventory._to_decimal(value) is value
    assert inventory._to_decimal(12.5) == Decimal("12.5")
    assert inventory._utcnow().tzinfo == timezone.utc