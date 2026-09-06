from typing import Generator

from sqlalchemy.orm import Session

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

from app.models.users import User
from app.utils.exceptions import AppError
from app.core.database import SessionLocal
from app.core.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl = "/api/v1/auth/login", description = "JWT Bearer Token")

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
        raise AppError(
            status_code=401,
            message="User not found"
        )

    if not user.is_active:
        raise AppError(
            status_code=403,
            message="Account is inactive"
        )

    return user

def require_role(*roles: str, strict: bool = False):
    """Guard a route by role.

    By default the check is hierarchical: ELEVATED_ROLES passes any list, so
    require_role("manager") also admits admin and superadmin. That is what makes
    the hierarchy work without enumerating roles on every endpoint — but it also
    means require_role("superadmin") does not restrict to superadmin.

    Pass strict=True to compare against the given roles only, skipping the
    hierarchy. That is the only way to express a superadmin-only endpoint.
    """
    if strict and not roles:
        raise ValueError("require_role(strict=True) needs at least one role")

    def checker(current_user: User = Depends(get_current_user)) -> User:
        role_name = getattr(getattr(current_user, "role", None), "name", None)
        if strict:
            if role_name in roles:
                return current_user
            raise AppError(status_code=403, message="Insufficient permissions")
        if not roles:
            return current_user  # no roles specified = any authenticated user
        if role_name in ELEVATED_ROLES or role_name in roles:
            return current_user
        raise AppError(status_code=403, message="Insufficient permissions")
    return checker
