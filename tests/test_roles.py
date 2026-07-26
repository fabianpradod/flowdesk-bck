from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def login_admin():
    response = client.post(
        "/api/v1/auth/login",
        json = {
            "email": "admin.demo@flowdesk.com",
            "password": "<DEMO_USER_PASSWORD>"
        }
    )

    assert response.status_code == 200
    return response.json()["access_token"]

def test_roles_require_authentication():
    response = client.get("/api/v1/roles")

    assert response.status_code == 401

def test_roles_invalid_token():
    response = client.get(
        "/api/v1/roles",
        headers = {
            "Authorization": "Bearer fake.token"
        }
    )

    assert response.status_code == 401

def test_admin_can_list_roles():
    token = login_admin()

    response = client.get(
        "/api/v1/roles",
        headers = {
            "Authorization": f"Bearer {token}"
        }
    )

    assert response.status_code == 200

    data = response.json()

    assert isinstance(data, list)
    assert len(data) >= 4

def test_default_roles_exist():
    token = login_admin()

    response = client.get(
        "/api/v1/roles",
        headers = {
            "Authorization": f"Bearer {token}"
        }
    )

    roles = {role["name"] for role in response.json()}

    assert "admin" in roles
    assert "employee" in roles
    assert "manager" in roles
    assert "superadmin" in roles

def test_role_schema():
    token = login_admin()

    response = client.get(
        "/api/v1/roles",
        headers = {
            "Authorization": f"Bearer {token}"
        }
    )

    role = response.json()[0]

    assert "id" in role
    assert "name" in role
    assert "description" in role

def test_employee_cannot_create_admin():
    employee_token = "employee-token"

    response = client.post(
        "/api/v1/auth/employees",
        headers = {
            "Authorization": f"Bearer {employee_token}"
        },
        json = {
            "email": "admin2@test.com",
            "role": "admin"
        }
    )
    assert response.status_code == 403

def test_employee_cannot_import_products():
    employee_token = "employee-token"

    response = client.post(
        "/api/v1/inventory/products/import",
        headers = {
            "Authorization": f"Bearer {employee_token}"
        }
    )
    assert response.status_code == 403

def test_admin_can_create_employee():
    token = login_admin()

    response = client.post(
        "/api/v1/auth/employees",
        headers = {
            "Authorization": f"Bearer {token}"
        },
        json = {
            "username": "employee_test",
            "email": "employee_test@flowdesk.com",
            "role_id": 4
        }
    )

    assert response.status_code in [200, 201]

def test_duplicate_employee_email():
    token = login_admin()

    payload = {
        "username": "employee_duplicate",
        "email": "duplicate@flowdesk.com",
        "role_id": 4
    }

    client.post(
        "/api/v1/auth/employees",
        headers = {
            "Authorization": f"Bearer {token}"
        },
        json = payload
    )

    response = client.post(
        "/api/v1/auth/employees",
        headers = {
            "Authorization": f"Bearer {token}"
        },
        json = payload
    )

    assert response.status_code == 400

def test_duplicate_username():
    token = login_admin()

    payload = {
        "username": "same_username",
        "email": "mail1@test.com",
        "role_id": 4
    }

    client.post(
        "/api/v1/auth/employees",
        headers = {
            "Authorization": f"Bearer {token}"
        },
        json = payload
    )

    payload["email"] = "mail2@test.com"

    response = client.post(
        "/api/v1/auth/employees",
        headers = {
            "Authorization": f"Bearer {token}"
        },
        json = payload
    )

    assert response.status_code == 400

def test_superadmin_can_create_company():
    superadmin_token = "superadmin-token"

    response = client.post(
        "/api/v1/companies",
        headers = {
            "Authorization": f"Bearer {superadmin_token}"
        },
        json = {
            "name": "Test Company"
        }
    )
    assert response.status_code in [200, 201]

def test_admin_cannot_create_superadmin():
    token = login_admin()

    response = client.post(
        "/api/v1/auth/employees",
        headers = {
            "Authorization": f"Bearer {token}"
        },
        json = {
            "username": "new_super",
            "email": "new_super@test.com",
            "role_id": 1
        }
    )

    assert response.status_code == 400

def test_invalid_role():
    token = login_admin()

    response = client.post(
        "/api/v1/auth/employees",
        headers = {
            "Authorization": f"Bearer {token}"
        },
        json = {
            "username": "userx",
            "email": "userx@test.com",
            "role_id": 999
        }
    )

    assert response.status_code == 404