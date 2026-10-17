from datetime import date
from decimal import Decimal
from io import BytesIO
from openpyxl import Workbook
import pytest
from app.services.importer import ImportFormatError, normalize_and_validate, read_rows, validate_upload

def test_csv_detection_mapping_preview_and_decimal_normalization():
    content = b"Type,Date,Currency,Subtotal,Tax\nINVOICE,2026-10-08,USD,1.000,50,100,50\n"
    # The comma in the number requires a semicolon-delimited source instead.
    content = "Type;Date;Currency;Subtotal;Tax\nINVOICE;2026-10-08;USD;1.000,50;100,00\n".encode()

    assert validate_upload("docs.csv", content, "text/csv") == "CSV"

    headers, rows = read_rows(content, "CSV")
    result = normalize_and_validate(rows, {"Type": "document_type", "Date": "issue_date", "Currency": "currency", "Subtotal": "subtotal", "Tax": "total_tax"})

    assert headers == ["Type", "Date", "Currency", "Subtotal", "Tax"]
    assert result["rows"][0]["data"]["subtotal"] == Decimal("1000.50")
    assert result["rows"][0]["data"]["issue_date"] == date(2026, 10, 8)

def test_ambiguous_date_requires_locale_and_invalid_rows_are_reported():
    content = b"type,date,currency\nINVOICE,08/10/2026,USD\n"
    _, rows = read_rows(content, "CSV")
    result = normalize_and_validate(rows, {"type": "document_type", "date": "issue_date", "currency": "currency"})

    assert result["errors"]

    result = normalize_and_validate(rows, {"type": "document_type", "date": "issue_date", "currency": "currency"}, locale="DMY")

    assert not result["errors"]
    assert result["rows"][0]["data"]["issue_date"] == date(2026, 10, 8)

def test_xlsx_is_read_as_values_and_formulas_are_rejected():
    workbook = Workbook(); sheet = workbook.active; sheet.title = "Docs"
    sheet.append(["document_type", "issue_date", "currency"]); sheet.append(["INVOICE", date(2026, 1, 1), "USD"])
    buffer = BytesIO(); workbook.save(buffer); content = buffer.getvalue()

    assert validate_upload("docs.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet") == "XLSX"

    headers, rows = read_rows(content, "XLSX", sheet="Docs")

    assert headers[0] == "document_type" and rows[0]["issue_date"].date() == date(2026, 1, 1)

    formula_book = Workbook(); formula_book.active.append(["document_type"]); formula_book.active.append(["=NOW()"])
    formula_buffer = BytesIO(); formula_book.save(formula_buffer)

    with pytest.raises(ImportFormatError): read_rows(formula_buffer.getvalue(), "XLSX")

def test_file_limits_and_invalid_format_are_rejected():
    with pytest.raises(ImportFormatError): validate_upload("docs.pdf", b"data", "application/pdf")
    with pytest.raises(ImportFormatError): validate_upload("docs.xlsx", b"not-a-zip", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")