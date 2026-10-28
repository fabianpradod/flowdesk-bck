"""The documented product import contract matches what the service accepts."""
from app.core.config import MAX_IMPORT_FILE_SIZE
from app.services.inventory import MAX_IMPORT_ROWS, PRODUCT_IMPORT_ALLOWED_COLUMNS, PRODUCT_IMPORT_REQUIRED_COLUMNS
from main import app


def _import_operation():
    return app.openapi()["paths"]["/api/v1/inventory/products/import"]["post"]


def test_import_description_lists_every_accepted_column():
    description = _import_operation()["description"]

    for column in PRODUCT_IMPORT_ALLOWED_COLUMNS:
        assert column in description


def test_import_description_names_both_formats_and_limits():
    description = _import_operation()["description"]

    assert ".csv" in description
    assert ".xlsx" in description
    assert f"{MAX_IMPORT_FILE_SIZE // (1024 * 1024)} MB" in description
    assert str(MAX_IMPORT_ROWS) in description


def test_import_description_drops_the_old_spreadsheet_headers():
    description = _import_operation()["description"]

    for old_header in ("Stock Actual", "Precio Estandar", "Estado"):
        assert old_header not in description


def test_required_columns_are_a_subset_of_the_accepted_ones():
    assert PRODUCT_IMPORT_REQUIRED_COLUMNS == {"sku", "nombre"}
    assert PRODUCT_IMPORT_REQUIRED_COLUMNS <= PRODUCT_IMPORT_ALLOWED_COLUMNS
