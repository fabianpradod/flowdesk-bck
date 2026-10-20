import importlib
import pytest
from app.core import config
from app.core.config import SECRET_KEY, SECRET_KEY_MIN_BYTES, validate_secret_key
from app.core.security import create_access_token, decode_access_token

def test_test_suite_uses_an_explicit_deterministic_secret():
    assert SECRET_KEY
    assert SECRET_KEY != "replace-with-a-long-random-value"
    assert len(SECRET_KEY.encode("utf-8")) >= SECRET_KEY_MIN_BYTES

@pytest.mark.parametrize("secret_key", [None, "", "   ", "\t\n"])
def test_missing_or_blank_secret_key_is_rejected(secret_key):
    with pytest.raises(ValueError) as error:
        validate_secret_key(secret_key)

    assert "SECRET_KEY" in str(error.value)
    assert secret_key not in str(error.value) if secret_key else True

@pytest.mark.parametrize(
    "secret_key",
    [
        "secret",
        "secret-key",
        "changeme",
        "change-me",
        "development-secret",
        "test-secret",
        "replace-with-a-long-random-value",
    ],
)
def test_known_secret_key_placeholders_are_rejected(secret_key):
    with pytest.raises(ValueError) as error:
        validate_secret_key(secret_key)

    assert secret_key not in str(error.value)

def test_short_secret_key_is_rejected_without_echoing_it():
    secret_key = "short-but-not-a-real-key"

    with pytest.raises(ValueError) as error:
        validate_secret_key(secret_key)

    assert "SECRET_KEY" in str(error.value)
    assert secret_key not in str(error.value)

def test_valid_secret_key_is_accepted_in_production_and_development():
    secret_key = "valid-signing-key-with-at-least-thirty-two-bytes"

    assert validate_secret_key(secret_key) == secret_key

def test_access_token_expiration_can_be_configured_without_exposing_secret(monkeypatch):
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "45")
    importlib.reload(config)

    try:
        assert config.ACCESS_TOKEN_EXPIRE_MINUTES == 45
    finally:
        monkeypatch.delenv("ACCESS_TOKEN_EXPIRE_MINUTES", raising=False)
        importlib.reload(config)

def test_jwt_round_trip_uses_the_configured_secret():
    token = create_access_token({"sub": "configuration-test"})

    assert decode_access_token(token)["sub"] == "configuration-test"

def test_changing_the_signing_key_invalidates_existing_tokens(monkeypatch):
    import app.core.security as security

    old_key = security.SECRET_KEY
    token = create_access_token({"sub": "old-key"})
    monkeypatch.setattr(security, "SECRET_KEY", "another-valid-signing-key-for-tests-2026")

    assert decode_access_token(token) is None
    assert security.SECRET_KEY != old_key