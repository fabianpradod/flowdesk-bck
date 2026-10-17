from datetime import date
from decimal import Decimal
from app.models.tenant.fiscal import FiscalDocument, FiscalDocumentLine, ImportBatch, TaxComponent
from app.models.tenant.registry import build_tenant_metadata, get_tenant_table_names
from app.schemas.fiscal import FiscalDocumentCreate, FiscalDocumentUpdate
from app.taxation.fiscal_adapter import document_tax_components, document_to_operations

def test_fiscal_tables_are_tenant_scoped_and_generic():
    schema = "tenant_" + "a" * 32
    metadata = build_tenant_metadata(schema)

    assert {metadata.tables[f"{schema}.{name}"].schema for name in ( "import_batch", "fiscal_document", "fiscal_document_line", "tax_component")} == {schema}
    assert {"import_batch", "fiscal_document", "fiscal_document_line", "tax_component"} <= set(get_tenant_table_names())

def test_document_schema_preserves_decimal_dates_currency_and_optional_lines():
    document = FiscalDocumentCreate(
        document_type="INVOICE", issue_date=date(2026, 1, 15), currency="USD",
        subtotal=Decimal("100.10"), taxable_base=Decimal("100.10"), total_tax=Decimal("10.01"), total=Decimal("110.11"),
        taxes=[{"tax_code": "VAT", "tax_type": "VAT", "category": "TAXABLE", "amount": "10.01"}],
    )

    assert document.issue_date == date(2026, 1, 15)
    assert document.total == Decimal("110.11")
    assert document.lines == []

def test_document_update_is_controlled():
    assert FiscalDocumentUpdate(status="CANCELLED").status == "CANCELLED"

    try:
        FiscalDocumentUpdate(total=Decimal("20"))

    except Exception:
        pass

    else:
        raise AssertionError("historical monetary fields must not be updateable")

def test_document_components_adapt_to_tax_engine_operations_without_calculating():
    operations = document_to_operations({
        "issue_date": date(2026, 1, 15),
        "taxes": [{"tax_code": "VAT", "category": "TAXABLE", "amount": Decimal("12.00")}],
        "lines": [{"taxes": [{"tax_code": "GST", "category": "ZERO_RATED", "amount": Decimal("0")}]}],
    })

    assert [operation.tax_code for operation in operations] == ["VAT", "GST"]
    assert operations[0].tax_amount == Decimal("12.00")
    assert operations[1].tax_category == "ZERO_RATED"

def test_document_aggregate_and_line_taxes_are_not_double_counted():
    document = {
        "id": "doc-1", "direction": "INPUT", "status": "ACTIVE",
        "taxes": [{"id": "document-vat", "tax_code": "VAT", "category": "TAXABLE", "amount": Decimal("30")}],
        "lines": [
            {"taxes": [{"id": "line-vat-1", "tax_code": "VAT", "category": "TAXABLE", "amount": Decimal("10")}]},
            {"taxes": [{"id": "line-vat-2", "tax_code": "VAT", "category": "TAXABLE", "amount": Decimal("20")}]}],
    }

    assert len(document_tax_components(document)) == 2

    operations = document_to_operations(document)

    assert len(operations) == 2
    assert sum((operation.tax_amount for operation in operations), Decimal("0")) == Decimal("30")