from sqlalchemy.orm import Session

from app.models.companies import Company
from app.models.users import User
from app.utils.exceptions import AppError


def list_companies(db: Session, current_user: User) -> list[Company]:
    role_name = getattr(getattr(current_user, "role", None), "name", None)
    if role_name != "superadmin":
        raise AppError(status_code=403, message="Insufficient permissions")
    return db.query(Company).order_by(Company.created_at.desc()).all()
