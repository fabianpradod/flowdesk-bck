from datetime import timedelta
from uuid import uuid4
import pytest
from app.core.config import DEMO_USER_PASSWORD
from app.core.security import create_access_token, decode_access_token, verify_password
from app.models.users import User
from app.services import auth as auth_service
from app.utils.exceptions import AppError
from main import app

def _user(email):
    return next(user for user in app.state.test_db.data[User] if user.email == email)

def _password_token(user, purpose, expires_delta=timedelta(hours=48)):
    return create_access_token(
        {"sub": str(user.id), "purpose": purpose},
        expires_delta=expires_delta,
    )

INVALID_PASSWORDS = [
    "",
    "a",
    "1234567",
    "        ",
    "12345678",
    "a" * 73,
    "á" * 37,
]

VALID_PASSWORDS = [
    "a" * 8,
    "a" * 72,
    "á" * 36,
    "valid pass",
    " valid pass ",
]

@pytest.mark.parametrize("password", INVALID_PASSWORDS)
def test_set_rejects_invalid_passwords_without_activating_or_consuming_invitation(client, password):
    pending = _user("inactive@test.com")
    pending.password = ""
    pending.is_active = False
    token = _password_token(pending, "set_password")

    response = client.post(
        "/api/v1/auth/password/set",
        json={"token": token, "new_password": password},
    )

    assert response.status_code == 422
    assert "input" not in response.json()["errors"][0]
    if len(password) > 1:
        assert password not in response.text
    assert pending.password == ""
    assert pending.is_active is False

    valid = "InvitePassword123!"
    accepted = client.post(
        "/api/v1/auth/password/set",
        json={"token": token, "new_password": valid},
    )
    assert accepted.status_code == 200
    assert pending.is_active is True
    assert verify_password(valid, pending.password)

@pytest.mark.parametrize("password", VALID_PASSWORDS)
def test_set_accepts_boundary_unicode_and_space_preserving_passwords(client, password):
    pending = _user("inactive@test.com")
    pending.password = ""
    pending.is_active = False
    token = _password_token(pending, "set_password")

    response = client.post(
        "/api/v1/auth/password/set",
        json={"token": token, "new_password": password},
    )

    assert response.status_code == 200
    assert pending.is_active is True
    assert verify_password(password, pending.password)
    assert client.post(
        "/api/v1/auth/login",
        json={"email": pending.email, "password": password},
    ).status_code == 200

@pytest.mark.parametrize("password", INVALID_PASSWORDS)
def test_reset_rejects_invalid_passwords_without_replacing_existing_hash(client, password):
    user = _user("admin.demo@flowdesk.com")
    previous_hash = user.password
    token = _password_token(user, "reset_password")

    response = client.post(
        "/api/v1/auth/password/reset",
        json={"token": token, "new_password": password},
    )

    assert response.status_code == 422
    assert "input" not in response.json()["errors"][0]
    if len(password) > 1:
        assert password not in response.text
    assert user.password == previous_hash
    assert user.is_active is True

    valid = "ResetPassword123!"
    accepted = client.post(
        "/api/v1/auth/password/reset",
        json={"token": token, "new_password": valid},
    )
    assert accepted.status_code == 200
    assert verify_password(valid, user.password)

@pytest.mark.parametrize("password", VALID_PASSWORDS)
def test_reset_accepts_boundary_unicode_and_space_preserving_passwords(client, password):
    user = _user("admin.demo@flowdesk.com")
    token = _password_token(user, "reset_password")

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

@pytest.mark.parametrize("path, email, purpose", [
    ("/api/v1/auth/password/set", "inactive@test.com", "set_password"),
    ("/api/v1/auth/password/reset", "admin.demo@flowdesk.com", "reset_password"),
])
def test_expired_tokens_cannot_change_password(client, path, email, purpose):
    user = _user(email)
    previous_password = user.password
    previous_active = user.is_active
    token = _password_token(user, purpose, timedelta(minutes=-1))

    response = client.post(
        path,
        json={"token": token, "new_password": "ValidPassword123!"},
    )

    assert response.status_code == 400
    assert user.password == previous_password
    assert user.is_active is previous_active

@pytest.mark.parametrize("path, email, purpose, wrong_purpose", [
    ("/api/v1/auth/password/set", "inactive@test.com", "set_password", "reset_password"),
    ("/api/v1/auth/password/reset", "admin.demo@flowdesk.com", "reset_password", "set_password"),
])
def test_tokens_with_the_wrong_purpose_cannot_change_password(
    client, path, email, purpose, wrong_purpose
):
    user = _user(email)
    previous_password = user.password
    token = _password_token(user, wrong_purpose)

    response = client.post(
        path,
        json={"token": token, "new_password": "ValidPassword123!"},
    )

    assert response.status_code == 400
    assert user.password == previous_password

@pytest.mark.parametrize("path, email, purpose", [
    ("/api/v1/auth/password/set", "inactive@test.com", "set_password"),
    ("/api/v1/auth/password/reset", "admin.demo@flowdesk.com", "reset_password"),
])
def test_nonexistent_user_token_cannot_change_password(client, path, email, purpose):
    user = _user(email)
    previous_password = user.password
    token = _password_token(type("UnknownUser", (), {"id": uuid4()})(), purpose)

    response = client.post(
        path,
        json={"token": token, "new_password": "ValidPassword123!"},
    )

    assert response.status_code == 404
    assert user.password == previous_password

@pytest.mark.parametrize("path, email", [
    ("/api/v1/auth/password/set", "inactive@test.com"),
    ("/api/v1/auth/password/reset", "admin.demo@flowdesk.com"),
])
def test_invalid_token_and_invalid_password_are_rejected_without_writes(client, path, email):
    user = _user(email)
    previous_password = user.password
    previous_active = user.is_active

    response = client.post(
        path,
        json={"token": "not-a-token", "new_password": "a" * 73},
    )

    assert response.status_code == 422
    assert user.password == previous_password
    assert user.is_active is previous_active

@pytest.mark.parametrize("missing_purpose", [False, True])
@pytest.mark.parametrize("path, email, purpose", [
    ("/api/v1/auth/password/set", "inactive@test.com", "set_password"),
    ("/api/v1/auth/password/reset", "admin.demo@flowdesk.com", "reset_password"),
])
def test_password_endpoints_reject_tampered_or_purposeless_tokens_without_writes(
    client, path, email, purpose, missing_purpose
):
    user = _user(email)
    previous_password = user.password
    previous_active = user.is_active
    claims = {"sub": str(user.id)}
    if not missing_purpose:
        claims["purpose"] = purpose
    token = _password_token(user, purpose) if not missing_purpose else create_access_token(claims)

    if not missing_purpose:
        parts = token.split(".")
        parts[-1] = ("A" if parts[-1][0] != "A" else "B") + parts[-1][1:]
        token = ".".join(parts)

    response = client.post(
        path,
        json={"token": token, "new_password": "NewValidPassword123!"},
    )

    assert response.status_code == 400
    assert response.json()["message"] == "Invalid or expired token"
    assert user.password == previous_password
    assert user.is_active is previous_active

def test_reset_rejects_reusing_current_password(client):
    user = _user("admin.demo@flowdesk.com")
    previous_hash = user.password
    token = _password_token(user, "reset_password")

    response = client.post(
        "/api/v1/auth/password/reset",
        json={"token": token, "new_password": DEMO_USER_PASSWORD},
    )

    assert response.status_code == 400
    assert response.json()["message"] == "New password cannot match current password"
    assert user.password == previous_hash

def test_forgot_password_only_creates_a_reset_token(monkeypatch, client):
    user = _user("admin.demo@flowdesk.com")
    sent = []
    monkeypatch.setattr(
        "app.services.auth.send_password_reset_email",
        lambda email, token: sent.append((email, token)),
    )

    response = client.post(
        "/api/v1/auth/password/forgot",
        json={"email": user.email, "password": "ShouldNotBeUsed123!"},
    )

    assert response.status_code == 200
    assert len(sent) == 1
    email, token = sent[0]
    assert email == user.email
    payload = decode_access_token(token)
    assert payload["sub"] == str(user.id)
    assert payload["purpose"] == "reset_password"
    assert "password" not in payload

@pytest.mark.parametrize("service", [auth_service.set_password, auth_service.reset_password])
def test_service_defense_rejects_invalid_password_before_database_access(service):
    class DatabaseMustNotBeQueried:
        def query(self, _model):
            raise AssertionError("invalid password reached the database")

    with pytest.raises(AppError) as refused:
        service("not-a-token", "a" * 73, DatabaseMustNotBeQueried())

    assert refused.value.status_code == 400
    assert refused.value.detail == "Invalid password"