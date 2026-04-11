from typing import Generator

from sqlalchemy.orm import Session

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

from app.models.users import User
from app.utils.exceptions import AppError
from app.core.database import SessionLocal
from app.core.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

ELEVATED_ROLES = {"admin", "superadmin"}

def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    payload = decode_access_token(token)
    if not payload:
        raise AppError(status_code=401, message="Invalid or expired token")

    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise AppError(status_code=401, message="Invalid or expired token")  # ← was 404

    return user

def require_role(*roles: str):
    def checker(current_user: User = Depends(get_current_user)) -> User:
        if not roles:
            return current_user  # no roles specified = everyone in
        if current_user.role.name in ELEVATED_ROLES or current_user.role.name in roles:
            return current_user
        raise AppError(status_code=403, message="Insufficient permissions")
    return checker