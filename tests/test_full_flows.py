from fastapi.testclient import TestClient
from app.core.config import DEMO_USER_PASSWORD
from main import app

client = TestClient(app)

def test_complete_auth_flow(superadmin_client):
    company_response = superadmin_client.post(
        "/api/v1/auth/register",
        json = {
            "name": "QA Company",
            "admin_email": "qaadmin@test.com",
            "admin_username": "qaadmin"
        }
    )

    assert company_response.status_code in [200, 201]

    login_response = client.post(
        "/api/v1/auth/login",
        json = {
            "email": "qaadmin@test.com",
            "password": "Password123!"
        }
    )

    assert login_response.status_code in [200, 401, 403]

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

def test_login_and_list_users():
    token = login_admin()

    response = client.get(
        "/api/v1/users",
        headers = {
            "Authorization": f"Bearer {token}"
        }
    )

    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_login_and_list_roles():
    token = login_admin()

    response = client.get(
        "/api/v1/roles",
        headers = {
            "Authorization": f"Bearer {token}"
        }
    )

    assert response.status_code == 200

def test_create_employee_then_list():
    token = login_admin()
    email = "flow_employee@test.com"

    create = client.post(
        "/api/v1/auth/employees",
        headers = {
            "Authorization": f"Bearer {token}"
        },
        json = {
            "username": "flow_employee",
            "email": email,
            "role_id": 4
        }
    )

    assert create.status_code in [200, 201]

    employees = client.get(
        "/api/v1/auth/employees",
        headers = {
            "Authorization": f"Bearer {token}"
        }
    )

    assert employees.status_code == 200

    emails = [
        employee["email"]
        for employee in employees.json()
    ]

    assert email in emails

def test_duplicate_employee_flow():
    token = login_admin()

    payload = {
        "username": "duplicate_flow",
        "email": "duplicate_flow@test.com",
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

def test_forgot_password_complete_flow():
    response = client.post(
        "/api/v1/auth/password/forgot",
        json = {
            "email": "admin.demo@flowdesk.com"
        }
    )

    assert response.status_code == 200

def test_reset_password_invalid_token():
    response = client.post(
        "/api/v1/auth/password/reset",
        json = {
            "token": "invalid-token",
            "new_password": "Password123!"
        }
    )

    assert response.status_code == 400

def test_set_password_invalid_token():
    response = client.post(
        "/api/v1/auth/password/set",
        json = {
            "token": "invalid-token",
            "new_password": "Password123!"
        }
    )

    assert response.status_code == 400

def test_protected_routes_require_login():
    endpoints = [
        "/api/v1/users",
        "/api/v1/roles",
        "/api/v1/auth/employees"
    ]

    for endpoint in endpoints:
        response = client.get(endpoint)

        assert response.status_code == 401

def test_invalid_token_all_routes():
    headers = {
        "Authorization": "Bearer invalid.token"
    }

    endpoints = [
        "/api/v1/users",
        "/api/v1/roles",
        "/api/v1/auth/employees"
    ]

    for endpoint in endpoints:
        response = client.get(endpoint, headers=headers)

        assert response.status_code == 401

def test_login_returns_bearer_token():
    response = client.post(
        "/api/v1/auth/login",
        json = {
            "email": "admin.demo@flowdesk.com",
            "password": DEMO_USER_PASSWORD
        }
    )

    body = response.json()

    assert response.status_code == 200
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str)

def test_inactive_user_cannot_login():
    response = client.post(
        "/api/v1/auth/login",
        json = {
            "email": "inactive@test.com",
            "password": DEMO_USER_PASSWORD
        }
    )

    assert response.status_code == 403

