import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_login_success():
    response = client.post(
        "/api/v1/auth/login",
        json = {
            "email":"admin.demo@flowdesk.com",
            "password":"<DEMO_USER_PASSWORD>"
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
    assert response.status_code in [400, 401]

def test_login_nonexistent_user():
    response = client.post(
        "/api/v1/auth/login",
        json = {
            "email": "fake@test.com",
            "password": "123456"
        }
    )
    assert response.status_code in [400, 401]

def test_login_inactive_user():
    response = client.post(
        "/api/v1/auth/login",
        json = {
            "email": "inactive@test.com",
            "password": "123456"
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
    assert response.status_code in [200, 400, 401]

def test_set_password():
    response = client.post(
        "/api/v1/auth/password/set",
        json = {
            "token": "fake-token",
            "password": "12345678"
        }
    )
    assert response.status_code in [200, 400, 401]

def test_reuse_old_password():
    response = client.post(
        "/api/v1/auth/password/reset",
        json = {
            "token": "fake-token",
            "new_password": "123456"
        }
    )
    assert response.status_code in [400, 401]

def test_login_without_password():
    response = client.post(
        "/api/v1/auth/login",
        json = {
            "email": "admin.demo@flowdesk.com",
            "password": ""
        }
    )

    assert response.status_code in [401,422]

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