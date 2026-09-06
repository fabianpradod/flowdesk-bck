from fastapi.testclient import TestClient
from app.core.config import DEMO_USER_PASSWORD
from main import app
import io

client = TestClient(app)

def login_admin():
    response = client.post(
        "/api/v1/auth/login",
        json = {
            "email": "admin.demo@flowdesk.com",
            "password": DEMO_USER_PASSWORD
        }
    )
    assert response.status_code == 200
    return response.json()["access_token"]

def test_import_empty_file():
    token = login_admin()
    file = io.BytesIO(b"")

    response = client.post(
        "/api/v1/inventory/products/import",
        headers = {
            "Authorization": f"Bearer {token}"
        },
        files = {
            "file": ("empty.csv", file, "text/csv")
        }
    )
    assert response.status_code == 400

def test_import_invalid_extension():
    token = login_admin()
    file = io.BytesIO(b"invalid")

    response = client.post(
        "/api/v1/inventory/products/import",
        headers = {
            "Authorization": f"Bearer {token}"
        },
        files = {
            "file": ("invalid.txt", file, "text/plain")
        }
    )
    assert response.status_code == 400

def test_import_missing_columns():
    token = login_admin()
    csv_content = b"name\nProduct"
    file = io.BytesIO(csv_content)

    response = client.post(
        "/api/v1/inventory/products/import",
        headers = {
            "Authorization": f"Bearer {token}"
        },
        files = {
            "file": ("products.csv", file, "text/csv")
        }
    )
    assert response.status_code == 400

def test_import_duplicate_sku():
    token = login_admin()
    csv_content = b"sku,name,stock\nSKU001,Test,10"
    file = io.BytesIO(csv_content)

    response = client.post(
        "/api/v1/inventory/products/import",
        headers = {
            "Authorization": f"Bearer {token}"
        },
        files = {
            "file": ("products.csv", file, "text/csv")
        }
    )
    assert response.status_code in [400, 409]

def test_csv_injection(client):
    token = login_admin()
    csv_content = b"sku,nombre\n=cmd|' /C calc'!A0,Product"
    file = io.BytesIO(csv_content)

    response = client.post(
        "/api/v1/inventory/products/import",
        headers = {
            "Authorization": f"Bearer {token}"
        },
        files = {
            "file": ("products.csv", file, "text/csv")
        }
    )
    assert response.status_code == 400


# ─── numeric validation on imported rows ──────────────────────────────────────

import pytest
from decimal import Decimal
from app.services.inventory import MAX_MONEY, MAX_QUANTITY, _parse_nonnegative_decimal
from app.utils.exceptions import ProductImportError
from app.services.inventory import parse_product_import_file


def parse_one(value, column="precio_venta", max_value=MAX_MONEY):
    errors = []
    result = _parse_nonnegative_decimal(value, column, 2, errors, max_value)
    return result, errors


@pytest.mark.parametrize("value", ["NaN", "nan", "Infinity", "-Infinity", "inf"])
def test_non_finite_values_are_reported_not_raised(value):
    """These parse as Decimal but blow up on comparison, so the import used to 500."""
    result, errors = parse_one(value)

    assert result == Decimal("0")
    assert errors[0]["code"] == "invalid_decimal"


def test_a_value_beyond_the_column_is_reported():
    result, errors = parse_one("100000000.00")

    assert result == Decimal("0")
    assert errors[0]["code"] == "decimal_too_large"


def test_the_column_maximum_itself_is_accepted():
    result, errors = parse_one(str(MAX_MONEY))

    assert result == MAX_MONEY
    assert errors == []


def test_quantities_use_the_wider_column_bound():
    result, errors = parse_one("9999999999.99", column="stock_minimo", max_value=MAX_QUANTITY)

    assert result == MAX_QUANTITY
    assert errors == []


def test_more_than_two_decimals_is_reported():
    result, errors = parse_one("12.345")

    assert result == Decimal("0")
    assert errors[0]["code"] == "too_many_decimals"


def test_negative_values_are_still_reported():
    result, errors = parse_one("-1.00")

    assert errors[0]["code"] == "negative_decimal"


def test_a_file_with_a_non_finite_price_fails_validation_cleanly():
    csv = b"sku,nombre,precio_venta\nSKU-1,Producto,NaN\n"

    with pytest.raises(ProductImportError) as error:
        parse_product_import_file("productos.csv", csv)

    assert error.value.status_code == 400
    assert error.value.code == "invalid_rows"
    assert error.value.errors[0]["code"] == "invalid_decimal"


def test_a_file_with_an_overflowing_price_fails_validation_cleanly():
    csv = b"sku,nombre,precio_venta\nSKU-1,Producto,999999999999\n"

    with pytest.raises(ProductImportError) as error:
        parse_product_import_file("productos.csv", csv)

    assert error.value.errors[0]["code"] == "decimal_too_large"
