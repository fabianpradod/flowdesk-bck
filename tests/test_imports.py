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