from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

@patch("app.services.email.send_password_set_email")
def test_invitation_email_sent(mock_send):
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
    assert mock_send.called

@patch("app.services.email.send_reset_password_email")
def test_reset_email_sent(mock_send):
    response = client.post(
        "/api/v1/auth/password/forgot",
        json={
            "email": "employee@test.com"
        }
    )
    assert response.status_code == 200
    assert mock_send.called

@patch("app.services.email.send_password_set_email")
def test_resend_invitation(mock_send):
    admin_token = "admin-token"

    response = client.post(
        "/api/v1/auth/invitation/resend",
        headers={
            "Authorization": f"Bearer {admin_token}"
        },
        json={
            "email": "employee@test.com"
        }
    )
    assert response.status_code == 200
    assert mock_send.called