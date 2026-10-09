from datetime import date
from decimal import Decimal
import pytest
from app.schemas.fiscal import ImportMappingCreate
from app.services.importer import ImportFormatError, normalize_and_validate, read_rows, validate_upload

def base_mapping():
    return {
        "Date": "document_date", "Type": "document_type", "Number": "number", "Currency": "currency",
        "Supplier ID": "issuer.tax_identifier", "Supplier": "issuer.name",
        "Base": "gross_amount", "Total": "total_amount",
        "Tax A": "taxes[0].tax_code", "Tax A amount": "taxes[0].tax_amount",
        "Tax A rate": "taxes[0].tax_rate", "Tax A category": "taxes[0].tax_category",
        "Retention": "taxes[1].withholding_amount", "Retention type": "taxes[1].withholding_type",
        "Retention flag": "taxes[1].is_withholding", "Retention code": "taxes[1].tax_code",
    }

def test_profile_settings_normalize_aliases_multiple_taxes_and_withholding():
    result = normalize_and_validate([{
        "Date": "08/10/2026", "Type": "INVOICE", "Number": "0007", "Currency": "USD",
        "Supplier ID": "001-123", "Supplier": "Provider", "Base": "1.234,56", "Total": "1.400,00",
        "Tax A": "TAX_A", "Tax A amount": "123,45", "Tax A rate": "10,00", "Tax A category": "STANDARD",
        "Retention": "20,00", "Retention type": "configured", "Retention flag": "true", "Retention code": "RET",
    }], base_mapping(), date_format="DMY", decimal_separator=",", thousands_separator=".")
    row = result["rows"][0]["data"]

    assert not result["errors"]
    assert row["issue_date"] == date(2026, 10, 8)
    assert row["document_number"] == "0007"
    assert row["subtotal"] == Decimal("1234.56")
    assert row["taxes"][0]["amount"] == Decimal("123.45")
    assert row["taxes"][1]["is_withholding"] is True
    assert row["issuer"]["tax_identifier"] == "001-123"

def test_group_by_builds_one_document_with_multiple_lines():
    mapping = {
        "Type": "document_type", "Date": "issue_date", "Currency": "currency", "Number": "document_number",
        "Description": "lines[0].description", "Qty": "lines[0].quantity", "Unit": "lines[0].unit_price",
        "Line base": "lines[0].line_base", "Line total": "lines[0].line_total",
    }
    result = normalize_and_validate([
        {"Type": "INVOICE", "Date": "2026-01-01", "Currency": "USD", "Number": "A-1", "Description": "One", "Qty": "1", "Unit": "10", "Line base": "10", "Line total": "10"},
        {"Type": "INVOICE", "Date": "2026-01-01", "Currency": "USD", "Number": "A-1", "Description": "Two", "Qty": "2", "Unit": "5", "Line base": "10", "Line total": "10"},
    ], mapping, group_by=["document_number"])

    assert result["rows_detected"] == 2
    assert len(result["rows"]) == 1
    assert result["rows"][0]["source_rows"] == [2, 3]
    assert len(result["rows"][0]["data"]["lines"]) == 2

def test_negative_decimal_is_reported_as_row_error_and_original_is_preserved():
    result = normalize_and_validate([{"Type": "INVOICE", "Date": "2026-01-01", "Currency": "USD", "Base": "-10"}], {
        "Type": "document_type", "Date": "issue_date", "Currency": "currency", "Base": "taxable_base",
    })

    assert result["errors"]
    assert result["rows"][0]["original"]["Base"] == "-10"

def test_import_mapping_can_be_used_as_a_reusable_import_profile():
    profile = ImportMappingCreate(
        name="Generic profile", description="Reusable source profile", source_type="CSV",
        mapping={"Date": "issue_date"}, encoding="utf-8", date_format="DMY",
        decimal_separator=",", thousands_separator=".", header_row=2, data_start_row=3,
        group_by=["document_number"], metadata={"owner": "tenant"},
    )

    assert profile.header_row == 2
    assert profile.group_by == ["document_number"]

def test_csv_profile_controls_encoding_header_and_data_rows():
    content = "metadata\nmetadata\nFecha;Número\n2026-01-01;0001\n".encode("latin-1")
    headers, rows = read_rows(content, "CSV", delimiter=";", encoding="latin-1", header_row=3, data_start_row=4)

    assert headers == ["Fecha", "Número"]
    assert rows == [{"Fecha": "2026-01-01", "Número": "0001"}]
    assert validate_upload("source.csv", content, "text/csv") == "CSV"

def test_malformed_csv_delimiter_is_a_normalized_import_error():
    with pytest.raises(ImportFormatError):
        read_rows(b"a\nb\nc\n", "CSV")