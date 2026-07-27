from app.core.security import hash_password, verify_password

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