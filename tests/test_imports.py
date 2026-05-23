from fastapi.testclient import TestClient
from main import app
import io

client = TestClient(app)

def test_import_empty_file():
    token = "admin-token"
    file = io.BytesIO(b"")

    response = client.post(
        "/api/v1/inventory/products/import",
        headers={
            "Authorization": f"Bearer {token}"
        },
        files={
            "file": ("empty.csv", file, "text/csv")
        }
    )
    assert response.status_code == 400

def test_import_invalid_extension():
    token = "admin-token"
    file = io.BytesIO(b"invalid")

    response = client.post(
        "/api/v1/inventory/products/import",
        headers={
            "Authorization": f"Bearer {token}"
        },
        files={
            "file": ("invalid.txt", file, "text/plain")
        }
    )
    assert response.status_code == 400

def test_import_missing_columns():
    token = "admin-token"
    csv_content = b"name\nProduct"
    file = io.BytesIO(csv_content)

    response = client.post(
        "/api/v1/inventory/products/import",
        headers={
            "Authorization": f"Bearer {token}"
        },
        files={
            "file": ("products.csv", file, "text/csv")
        }
    )
    assert response.status_code == 400

def test_import_duplicate_sku():
    token = "admin-token"
    csv_content = b"sku,name,stock\nSKU001,Test,10"
    file = io.BytesIO(csv_content)

    response = client.post(
        "/api/v1/inventory/products/import",
        headers={
            "Authorization": f"Bearer {token}"
        },
        files={
            "file": ("products.csv", file, "text/csv")
        }
    )
    assert response.status_code in [400, 409]

def test_csv_injection(client):
    token = "admin-token"
    csv_content = b"sku,nombre\n=cmd|' /C calc'!A0,Product"
    file = io.BytesIO(csv_content)

    response = client.post(
        "/api/v1/inventory/products/import",
        headers={
            "Authorization": f"Bearer {token}"
        },
        files={
            "file": ("products.csv", file, "text/csv")
        }
    )
    assert response.status_code == 400