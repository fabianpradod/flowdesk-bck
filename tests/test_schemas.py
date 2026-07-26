import pytest
from pydantic import ValidationError
from app.schemas.users import EmailRequest, PasswordReset, PasswordSet, UserLogin

def test_user_login_schema():
    data = UserLogin(
        email = "user@test.com",
        password = "Password123!",
    )

    assert data.email == "user@test.com"
    assert data.password == "Password123!"

def test_user_login_invalid_email():
    with pytest.raises(ValidationError):
        UserLogin(
            email = "correo_invalido",
            password = "Password123!",
        )

def test_email_request():
    data = EmailRequest(
        email = "user@test.com",
    )

    assert data.email == "user@test.com"

def test_email_request_invalid():
    with pytest.raises(ValidationError):
        EmailRequest(
            email = "abc",
        )

def test_password_set():
    data = PasswordSet(
        token = "abc123",
        new_password = "Password123!",
    )

    assert data.token == "abc123"

def test_password_reset():
    data = PasswordReset(
        token = "abc123",
        new_password = "Password123!",
    )

    assert data.token == "abc123"