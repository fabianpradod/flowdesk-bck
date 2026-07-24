from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app
from unittest.mock import patch
from app.api.dependencies.auth import get_current_user
from tests.auth_helpers import admin_user

client = TestClient(app)

def override_admin():
    return admin_user()

@patch("app.services.auth.send_password_set_email")
def test_invitation_email_sent(mock_send):
    app.dependency_overrides[get_current_user] = override_admin

    client = TestClient(app)

    response = client.post(
        "/api/v1/auth/employees",
        json = {
            "username": "employee01",
            "email": "employee@test.com",
            "role_id": 4
        }
    )

    app.dependency_overrides.clear()

    assert response.status_code in [200,201]
    mock_send.assert_called_once()

@patch("app.services.auth.send_password_reset_email")
def test_reset_email_sent(mock_send):
    response = client.post(
        "/api/v1/auth/password/forgot",
        json = {
            "email": "employee@test.com"
        }
    )

    assert response.status_code == 200
    mock_send.assert_called_once()

@patch("app.services.auth.send_password_set_email")
def test_resend_invitation(mock_send):
    app.dependency_overrides[get_current_user] = override_admin

    client = TestClient(app)

    response = client.post(
        "/api/v1/auth/invitations/resend",
        json = {
            "email":"employee@test.com"
        }
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    mock_send.assert_called_once()

@patch("app.services.auth.send_password_set_email")
def test_resend_invitation_unknown_user(mock_send):
    app.dependency_overrides[get_current_user] = override_admin

    client = TestClient(app)

    response = client.post(
        "/api/v1/auth/invitations/resend",
        json = {
            "email":"noexiste@test.com"
        }
    )

    app.dependency_overrides.clear()

    assert response.status_code == 404
    mock_send.assert_not_called()

@patch("app.services.auth.send_password_reset_email")
def test_forgot_password_unknown_email(mock_send):
    response = client.post(
        "/api/v1/auth/password/forgot",
        json = {
            "email":"noexiste@test.com"
        }
    )

    assert response.status_code == 200
    mock_send.assert_not_called()

def test_forgot_password_invalid_payload():
    response = client.post(
        "/api/v1/auth/password/forgot",
        json = {}
    )

    assert response.status_code == 422

@patch("app.services.auth.send_password_reset_email")
def test_forgot_password_rate_limit(mock_send):
    email = "admin.demo@flowdesk.com"

    for _ in range(3):
        client.post(
            "/api/v1/auth/password/forgot",
            json = {
                "email": email
            }
        )

    response = client.post(
        "/api/v1/auth/password/forgot",
        json = {
            "email": email
        }
    )

    assert response.status_code == 429

@patch("app.services.auth.send_password_reset_email", side_effect=Exception("SMTP Error"))
def test_forgot_password_email_failure(_):
    response = client.post(
        "/api/v1/auth/password/forgot",
        json = {
            "email":"admin.demo@flowdesk.com"
        }
    )

    assert response.status_code == 200