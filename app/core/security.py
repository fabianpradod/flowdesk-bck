from uuid import UUID

from jose import JWTError, jwt
from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext
from app.core.config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_BYTES = 72
COMMON_WEAK_PASSWORDS = frozenset({
    "12345678",
    "admin123",
    "letmein",
    "password123",
    "qwerty123",
    "qwertyui",
})

def validate_password(password: str) -> str:
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters long")
    if password.isspace():
        raise ValueError("Password cannot contain only whitespace")
    try:
        password_bytes = password.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("Password contains invalid characters") from exc
    if len(password_bytes) > PASSWORD_MAX_BYTES:
        raise ValueError(f"Password cannot exceed {PASSWORD_MAX_BYTES} UTF-8 bytes")
    if password.casefold() in COMMON_WEAK_PASSWORDS:
        raise ValueError("Password is too common")
    return password

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None

def token_subject(payload: dict) -> UUID | None:
    """The user id in a decoded token, or None when sub is missing or not a UUID.

    Reading payload["sub"] directly raised KeyError on a token without it, and a
    non UUID value only failed later on the database cast. Both answered 500.
    """
    try:
        return UUID(str(payload["sub"]))
    except (KeyError, ValueError):
        return None
