from app.core.security import (
    PASSWORD_MAX_BYTES,
    PASSWORD_MIN_LENGTH,
    hash_password,
    validate_password,
    verify_password,
)

def test_password_policy_accepts_the_minimum_and_maximum():
    assert validate_password("a" * PASSWORD_MIN_LENGTH) == "a" * PASSWORD_MIN_LENGTH
    assert validate_password("a" * PASSWORD_MAX_BYTES) == "a" * PASSWORD_MAX_BYTES

def test_password_policy_rejects_empty_whitespace_short_common_and_long_values():
    for password in ("", "        ", "short", "12345678", "a" * (PASSWORD_MAX_BYTES + 1)):
        try:
            validate_password(password)
        except ValueError:
            continue
        raise AssertionError(f"password should be rejected: {password!r}")

def test_password_policy_counts_utf8_bytes_and_preserves_unicode():
    password = "á" * 36  # 36 code points, 72 UTF-8 bytes
    assert validate_password(password) == password

    try:
        validate_password("á" * 37)
    except ValueError:
        pass
    else:
        raise AssertionError("a password over bcrypt's UTF-8 byte limit was accepted")

def test_password_policy_preserves_leading_trailing_and_internal_spaces():
    password = " abc de "
    assert validate_password(password) == password

def test_hash_password():
    password = "Password123!"
    hashed = hash_password(password)

    assert hashed != password
    assert isinstance(hashed, str)

def test_verify_password():
    password = "Password123!"
    hashed = hash_password(password)

    assert verify_password(password, hashed)

def test_wrong_password():
    hashed = hash_password("Password123!")

    assert not verify_password("WrongPassword", hashed)

def test_hash_is_different_each_time():
    password = "Password123!"
    first = hash_password(password)
    second = hash_password(password)

    assert first != second