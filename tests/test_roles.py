from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_employee_cannot_create_admin():
    employee_token = "employee-token"

    response = client.post(
        "/api/v1/auth/employees",
        headers={
            "Authorization": f"Bearer {employee_token}"
        },
        json={
            "email": "admin2@test.com",
            "role": "admin"
        }
    )
    assert response.status_code == 403

def test_employee_cannot_import_products():
    employee_token = "employee-token"

    response = client.post(
        "/api/v1/inventory/products/import",
        headers={
            "Authorization": f"Bearer {employee_token}"
        }
    )
    assert response.status_code == 403

def test_admin_can_create_employee():
    admin_token = "admin-token"

    response = client.post(
        "/api/v1/auth/employees",
        headers={
            "Authorization": f"Bearer {admin_token}"
        },
        json={
            "email": "employee@test.com",
            "role": "employee"
        }
    )
    assert response.status_code in [200, 201]

def test_superadmin_can_create_company():
    superadmin_token = "superadmin-token"

    response = client.post(
        "/api/v1/companies",
        headers={
            "Authorization": f"Bearer {superadmin_token}"
        },
        json={
            "name": "Test Company"
        }
    )
    assert response.status_code in [200, 201]