import time
from datetime import timedelta
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password

def test_create_token():
    token = create_access_token(
        {
            "sub": "123",
            "role": "admin",
            "company_id": "456",
        }
    )

    assert isinstance(token, str)
    assert len(token) > 20

def test_decode_valid_token():
    token = create_access_token(
        {
            "sub": "123",
            "role": "admin",
            "company_id": "456",
        }
    )

    payload = decode_access_token(token)

    assert payload["sub"] == "123"
    assert payload["role"] == "admin"
    assert payload["company_id"] == "456"

def test_decode_invalid_token():
    payload = decode_access_token("abc.def.ghi")

    assert payload is None

def test_decode_expired_token():
    token = create_access_token(
        {"sub": "1", "role": "admin"},
        expires_delta=timedelta(seconds=-1),
    )

    payload = decode_access_token(token)

    assert payload is None

def test_payload_contains_exp():
    token = create_access_token(
        {
            "sub": "123",
            "role": "admin",
        }
    )

    payload = decode_access_token(token)

    assert "exp" in payload

def test_hash_password_changes_value():
    password = "Password123!"
    hashed = hash_password(password)

    assert hashed != password

def test_verify_password_success():
    password = "Password123!"
    hashed = hash_password(password)

    assert verify_password(password, hashed)

def test_verify_password_failure():
    hashed = hash_password("Password123!")

    assert not verify_password("WrongPassword", hashed)

def test_create_and_decode_token():
    token = create_access_token({"sub": "admin@test.com"})
    payload = decode_access_token(token)

    assert payload["sub"] == "admin@test.com"

def test_decode_invalid_token_returns_none():
    payload = decode_access_token("abc.def.ghi")

    assert payload is None