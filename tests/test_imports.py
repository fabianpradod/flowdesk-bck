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


# ─── upload size limit ────────────────────────────────────────────────────────

from app.core.config import MAX_IMPORT_FILE_SIZE
from app.services.inventory import IMPORT_READ_CHUNK, read_import_upload


class CountingUpload:
    """Serves a payload in chunks and records how much was actually read."""

    def __init__(self, payload: bytes):
        self._stream = io.BytesIO(payload)
        self.bytes_read = 0
        self.file = self

    def read(self, size=-1):
        chunk = self._stream.read(size)
        self.bytes_read += len(chunk)
        return chunk


def test_an_upload_within_the_limit_is_read_whole():
    payload = b"x" * (IMPORT_READ_CHUNK * 2)
    upload = CountingUpload(payload)

    assert read_import_upload(upload) == payload


def test_an_oversized_upload_is_refused():
    upload = CountingUpload(b"x" * (MAX_IMPORT_FILE_SIZE + 1))

    with pytest.raises(ProductImportError) as error:
        read_import_upload(upload)

    assert error.value.status_code == 400
    assert error.value.code == "file_too_large"


def test_an_oversized_upload_is_not_buffered_in_full():
    """The point of the change: it stops reading instead of loading everything."""
    oversized = MAX_IMPORT_FILE_SIZE * 4
    upload = CountingUpload(b"x" * oversized)

    with pytest.raises(ProductImportError):
        read_import_upload(upload)

    assert upload.bytes_read <= MAX_IMPORT_FILE_SIZE + IMPORT_READ_CHUNK
    assert upload.bytes_read < oversized


def test_a_payload_at_the_exact_limit_is_accepted():
    payload = b"x" * MAX_IMPORT_FILE_SIZE
    upload = CountingUpload(payload)

    assert len(read_import_upload(upload)) == MAX_IMPORT_FILE_SIZE


def test_the_limit_also_holds_when_the_service_is_called_directly():
    oversized = b"x" * (MAX_IMPORT_FILE_SIZE + 1)

    with pytest.raises(ProductImportError) as error:
        parse_product_import_file("productos.csv", oversized)

    assert error.value.code == "file_too_large"


def test_the_endpoint_refuses_an_oversized_file():
    token = login_admin()
    file = io.BytesIO(b"x" * (MAX_IMPORT_FILE_SIZE + 1))

    response = client.post(
        "/api/v1/inventory/products/import",
        headers = {"Authorization": f"Bearer {token}"},
        files = {"file": ("productos.csv", file, "text/csv")},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "file_too_large"
