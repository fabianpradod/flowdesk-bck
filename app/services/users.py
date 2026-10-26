from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from uuid import UUID
from app.models.users import User
from app.models.roles import Role
from app.schemas.users import UserUpdate, UserStatusUpdate
from app.utils.exceptions import AppError
from app.utils.logger import logger


def get_users(db: Session, current_user) -> list[User]:
    if current_user.role.name == "superadmin":
        return db.query(User).join(Role).all()
    return db.query(User).join(Role).filter(User.company_id == current_user.company_id).all()


def update_user(db: Session, user_id: UUID, data: UserUpdate, current_user) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise AppError(404, "User not found")
    if user.role.name == "superadmin":
        raise AppError(403, "Cannot modify a superadmin user")
    # Another company's user answers like a missing one. A 403 told an admin that
    # the id exists in some other company.
    if current_user.role.name != "superadmin" and user.company_id != current_user.company_id:
        raise AppError(404, "User not found")

    # Every rule is checked before the first field changes, so a refused request
    # never leaves part of its fields applied.
    changes = {}
    if data.username is not None and data.username != user.username:
        _assert_username_available(db, data.username)
        changes["username"] = data.username
    if data.role_id is not None and data.role_id != user.role_id:
        if user.id == current_user.id:
            raise AppError(400, "Cannot change your own role")
        role = db.query(Role).filter(Role.id == data.role_id).first()
        if not role:
            raise AppError(404, "Role not found")
        if role.name == "superadmin":
            raise AppError(403, "Cannot assign superadmin role")
        changes["role_id"] = data.role_id
    if data.is_active is not None and data.is_active != user.is_active:
        if user.id == current_user.id:
            raise AppError(400, "Cannot change your own status")
        changes["is_active"] = data.is_active

    for field, value in changes.items():
        setattr(user, field, value)
    _commit_user_changes(db, user_id)
    db.refresh(user)
    return user


def update_user_status(db: Session, user_id: UUID, data: UserStatusUpdate, current_user) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise AppError(404, "User not found")
    if user.id == current_user.id:
        raise AppError(400, "Cannot change your own status")
    if user.role.name == "superadmin":
        raise AppError(403, "Cannot modify a superadmin user")
    if current_user.role.name != "superadmin" and user.company_id != current_user.company_id:
        raise AppError(404, "User not found")

    user.is_active = data.is_active
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user_id: UUID, current_user) -> None:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise AppError(404, "User not found")
    if user.id == current_user.id:
        raise AppError(400, "Cannot delete your own account")
    if user.role.name == "superadmin":
        raise AppError(403, "Cannot delete a superadmin user")
    if current_user.role.name != "superadmin" and user.company_id != current_user.company_id:
        raise AppError(404, "User not found")

    user.is_active = False
    db.commit()


def _assert_username_available(db: Session, username: str) -> None:
    # Usernames are unique across companies; without this check the unique
    # index caught the duplicate and the request answered 500.
    if db.query(User).filter(User.username == username).first():
        raise AppError(400, "Username already registered")


def _commit_user_changes(db: Session, user_id: UUID) -> None:
    try:
        db.commit()
    except IntegrityError:
        # Another request took the username between the check and the commit.
        db.rollback()
        raise AppError(400, "Username already registered")
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Failed to update user %s", user_id)
        raise AppError(500, "Failed to update user")
