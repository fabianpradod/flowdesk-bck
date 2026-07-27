from io import BytesIO
import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from app.core.config import DEMO_USER_PASSWORD
from main import app

client = TestClient(app)

def login_admin(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "admin.demo@flowdesk.com",
            "password": DEMO_USER_PASSWORD,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    return body["access_token"]

def build_valid_import_xlsx() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(
        [
            "ID",
            "Nombre",
            "Stock Actual",
            "Stock Minimo",
            "Precio",
            "Proveedor",
            "Descripcion",
            "Estado",
        ]
    )
    sheet.append(
        [
            None,
            "Producto demo",
            10,
            5,
            12.50,
            "Proveedor demo",
            "Descripcion demo",
            "Activo",
        ]
    )

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()

def test_roles_require_authentication(client):
    response = client.get("/api/v1/roles")
    assert response.status_code == 401

def test_roles_invalid_token(client):
    response = client.get(
        "/api/v1/roles",
        headers={"Authorization": "Bearer fake.token"},
    )
    assert response.status_code == 401

def test_admin_can_list_roles(client):
    token = login_admin(client)

    response = client.get(
        "/api/v1/roles",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 4

def test_default_roles_exist(client):
    token = login_admin(client)

    response = client.get(
        "/api/v1/roles",
        headers={"Authorization": f"Bearer {token}"},
    )

    roles = {role["name"] for role in response.json()}

    assert "admin" in roles
    assert "employee" in roles
    assert "manager" in roles
    assert "superadmin" in roles

def test_role_schema(client):
    token = login_admin(client)

    response = client.get(
        "/api/v1/roles",
        headers={"Authorization": f"Bearer {token}"},
    )

    role = response.json()[0]

    assert "id" in role
    assert "name" in role
    assert "description" in role

def test_employee_cannot_create_admin(employee_client):
    response = employee_client.post(
        "/api/v1/auth/employees",
        json={
            "username": "employee1",
            "email": "employee1@test.com",
            "role_id": 4,
        },
    )
    assert response.status_code == 403

def test_employee_cannot_import_products(employee_client):
    response = employee_client.post(
        "/api/v1/inventory/products/import",
        files={
            "file": (
                "products.xlsx",
                build_valid_import_xlsx(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 403

def test_admin_can_create_employee(client):
    token = login_admin(client)

    response = client.post(
        "/api/v1/auth/employees",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "username": "employee_test",
            "email": "employee_test@flowdesk.com",
            "role_id": 4,
        },
    )

    assert response.status_code in [200, 201]

def test_duplicate_employee_email(client):
    token = login_admin(client)

    payload = {
        "username": "employee_duplicate",
        "email": "duplicate@flowdesk.com",
        "role_id": 4,
    }

    first = client.post(
        "/api/v1/auth/employees",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    assert first.status_code in [200, 201]

    response = client.post(
        "/api/v1/auth/employees",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )

    assert response.status_code == 400

def test_duplicate_username(client):
    token = login_admin(client)

    payload = {
        "username": "same_username",
        "email": "mail1@test.com",
        "role_id": 4,
    }

    first = client.post(
        "/api/v1/auth/employees",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    assert first.status_code in [200, 201]

    payload["email"] = "mail2@test.com"

    response = client.post(
        "/api/v1/auth/employees",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )

    assert response.status_code == 400

def test_superadmin_can_create_company(client):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Test Company",
            "admin_username": "company_admin",
            "admin_email": "company_admin@test.com",
        },
    )
    assert response.status_code in [200, 201]

def test_admin_cannot_create_superadmin(client):
    token = login_admin(client)

    response = client.post(
        "/api/v1/auth/employees",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "username": "new_super",
            "email": "new_super@test.com",
            "role_id": 1,
        },
    )

    assert response.status_code == 400

def test_invalid_role(client):
    token = login_admin(client)

    response = client.post(
        "/api/v1/auth/employees",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "username": "userx",
            "email": "userx@test.com",
            "role_id": 999,
        },
    )

    assert response.status_code == 404