from sqlalchemy.orm import Session
from uuid import UUID
from app.models.users import User
from app.models.roles import Role
from app.schemas.users import UserUpdate, UserStatusUpdate
from app.utils.exceptions import AppError


def get_users(db: Session, current_user) -> list[User]:
    if current_user.role.name == "superadmin":
        return db.query(User).join(Role).all()
    return db.query(User).join(Role).filter(User.company_id == current_user.company_id).all()

def update_user(db: Session, user_id: UUID, data: UserUpdate, current_user) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise AppError(404, "User not found")
    if current_user.role.name != "superadmin" and user.company_id != current_user.company_id:
        raise AppError(403, "Not authorized")
    if data.username is not None:
        user.username = data.username
    if data.role_id is not None:
        role = db.query(Role).filter(Role.id == data.role_id).first()
        if not role:
            raise AppError(404, "Role not found")
        user.role_id = data.role_id
    db.commit()
    db.refresh(user)
    return user

def update_user_status(db: Session, user_id: UUID, data: UserStatusUpdate, current_user) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise AppError(404, "User not found")
    if current_user.role.name != "superadmin" and user.company_id != current_user.company_id:
        raise AppError(403, "Not authorized")
    user.is_active = data.is_active
    db.commit()
    db.refresh(user)
    return user

def delete_user(db: Session, user_id: UUID, current_user) -> None:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise AppError(404, "User not found")
    if current_user.role.name != "superadmin" and user.company_id != current_user.company_id:
        raise AppError(403, "Not authorized")
    user.is_active = False
    db.commit()