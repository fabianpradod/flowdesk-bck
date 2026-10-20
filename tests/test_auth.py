from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from main import app
from app.core.config import DEMO_USER_PASSWORD
from app.core.security import create_access_token, verify_password
from app.models.users import User

client = TestClient(app)

def test_login_success():
    response = client.post(
        "/api/v1/auth/login",
        json = {
            "email":"admin.demo@flowdesk.com",
            "password": DEMO_USER_PASSWORD
        }
    )
    assert response.status_code == 200
    assert "access_token" in response.json()

def test_login_invalid_password():
    response = client.post(
        "/api/v1/auth/login",
        json = {
            "email": "admin@test.com",
            "password": "wrongpassword"
        }
    )
    assert response.status_code == 401
    assert response.json()["message"] == "Invalid credentials"

def test_login_nonexistent_user():
    response = client.post(
        "/api/v1/auth/login",
        json = {
            "email": "fake@test.com",
            "password": "123456"
        }
    )
    assert response.status_code == 401
    assert response.json()["message"] == "Invalid credentials"

def test_login_does_not_disclose_user_existence():
    invalid_password = client.post(
        "/api/v1/auth/login",
        json={"email": "admin.demo@flowdesk.com", "password": "WrongPassword123!"},
    )
    unknown_user = client.post(
        "/api/v1/auth/login",
        json={"email": "missing-user@test.com", "password": "WrongPassword123!"},
    )

    assert invalid_password.status_code == 401
    assert unknown_user.status_code == 401
    assert invalid_password.json() == unknown_user.json()

def test_login_inactive_user():
    response = client.post(
        "/api/v1/auth/login",
        json = {
            "email": "inactive@test.com",
            "password": DEMO_USER_PASSWORD
        }
    )
    assert response.status_code == 403

def test_invalid_token_access():
    response = client.get(
        "/api/v1/inventory/products",
        headers = {
            "Authorization": "Bearer invalidtoken"
        }
    )
    assert response.status_code == 401

def test_reset_password():
    response = client.post(
        "/api/v1/auth/password/reset",
        json = {
            "token": "fake-token",
            "new_password": "newpassword123"
        }
    )
    assert response.status_code == 400

def test_set_password():
    response = client.post(
        "/api/v1/auth/password/set",
        json = {
            "token":"fake-token",
            "new_password":"SetPassword123!"
        }
    )
    assert response.status_code == 400

def test_reuse_old_password():
    response = client.post(
        "/api/v1/auth/password/reset",
        json = {
            "token": "fake-token",
            "new_password": "AnotherPassword123!"
        }
    )
    assert response.status_code == 400

def test_login_without_password():
    response = client.post(
        "/api/v1/auth/login",
        json = {
            "email": "admin.demo@flowdesk.com",
            "password": ""
        }
    )

    assert response.status_code == 401

def test_login_invalid_payload():
    response = client.post(
        "/api/v1/auth/login",
        json = {}
    )

    assert response.status_code == 422

def test_invalid_jwt():
    response = client.get(
        "/api/v1/users",
        headers = {
            "Authorization":"Bearer abc.def.ghi"
        }
    )

    assert response.status_code == 401

def test_forgot_password_unknown_email():
    response = client.post(
        "/api/v1/auth/password/forgot",
        json = {
            "email":"noexiste@test.com"
        }
    )

    assert response.status_code == 200

def test_forgot_password_rate_limit():
    email = "admin.demo@flowdesk.com"

    for _ in range(3):
        client.post(
            "/api/v1/auth/password/forgot",
            json = {"email":email}
        )

    response = client.post(
        "/api/v1/auth/password/forgot",
        json = {"email":email}
    )

    assert response.status_code==429

def test_register_duplicate_email(superadmin_client):
    response = superadmin_client.post(
        "/api/v1/auth/register",
        json = {
            "name": "Empresa Test",
            "admin_username": "nuevoadmin",
            "admin_email": "admin.demo@flowdesk.com"
        }
    )

    assert response.status_code == 400

def test_register_duplicate_username(superadmin_client):
    response = superadmin_client.post(
        "/api/v1/auth/register",
        json = {
            "name": "Empresa Test",
            "admin_username": "demo_admin",
            "admin_email": "nuevo@test.com"
        }
    )

    assert response.status_code == 400

def test_forgot_password_invalid_payload():
    response = client.post(
        "/api/v1/auth/password/forgot",
        json = {}
    )

    assert response.status_code == 422

def test_reset_password_invalid_payload():
    response = client.post(
        "/api/v1/auth/password/reset",
        json = {}
    )

    assert response.status_code == 422

def test_set_password_invalid_payload():
    response = client.post(
        "/api/v1/auth/password/set",
        json = {}
    )

    assert response.status_code == 422

def test_reset_password_empty_token():
    response = client.post(
        "/api/v1/auth/password/reset",
        json = {
            "token":"",
            "new_password":"Password123!"
        }
    )

    assert response.status_code == 400

def test_set_password_empty_token():
    response = client.post(
        "/api/v1/auth/password/set",
        json = {
            "token":"",
            "new_password":"Password123!"
        }
    )

    assert response.status_code == 400

def test_login_invalid_email_format():
    response = client.post(
        "/api/v1/auth/login",
        json = {
            "email":"correoinvalido",
            "password":"123456"
        }
    )

    assert response.status_code == 422

def test_forgot_password_invalid_email():
    response = client.post(
        "/api/v1/auth/password/forgot",
        json = {
            "email":"correo"
        }
    )

    assert response.status_code == 422

def test_register_invalid_payload(superadmin_client):
    response = superadmin_client.post(
        "/api/v1/auth/register",
        json = {}
    )

    assert response.status_code == 422

def test_set_password_uses_policy_and_result_can_login():
    pending = next(user for user in app.state.test_db.data[User] if user.email == "inactive@test.com")
    pending.password = ""
    token = create_access_token(
        {"sub": str(pending.id), "purpose": "set_password"},
        expires_delta=timedelta(hours=48),
    )
    password = " invite pass "

    response = client.post(
        "/api/v1/auth/password/set",
        json={"token": token, "new_password": password},
    )

    assert response.status_code == 200
    assert verify_password(password, pending.password)
    assert client.post(
        "/api/v1/auth/login",
        json={"email": pending.email, "password": password},
    ).status_code == 200

def test_reset_password_uses_policy_and_result_can_login():
    user = next(user for user in app.state.test_db.data[User] if user.email == "admin.demo@flowdesk.com")
    token = create_access_token(
        {"sub": str(user.id), "purpose": "reset_password"},
        expires_delta=timedelta(hours=48),
    )
    password = " reset pass "

    response = client.post(
        "/api/v1/auth/password/reset",
        json={"token": token, "new_password": password},
    )

    assert response.status_code == 200
    assert verify_password(password, user.password)
    assert client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": password},
    ).status_code == 200

@pytest.mark.parametrize("path", ["/api/v1/auth/password/set", "/api/v1/auth/password/reset"])
def test_password_endpoints_reject_invalid_passwords_before_writing(path):
    password = "a" * 73
    response = client.post(path, json={"token": "valid-shaped-token", "new_password": password})

    assert response.status_code == 422