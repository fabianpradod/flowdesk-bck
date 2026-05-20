from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from uuid import UUID
from app.api.dependencies.auth import get_db, get_current_user, require_role
from app.schemas.users import UserResponse, UserUpdate, UserStatusUpdate
import app.services.users as users_service

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("", response_model=list[UserResponse])
def get_users(db: Session = Depends(get_db), current_user=Depends(require_role("admin", "superadmin"))):
    return users_service.get_users(db, current_user)


@router.put("/{user_id}", response_model=UserResponse)
def update_user(user_id: UUID, data: UserUpdate, db: Session = Depends(get_db), current_user=Depends(require_role("admin", "superadmin"))):
    return users_service.update_user(db, user_id, data, current_user)


@router.patch("/{user_id}/status", response_model=UserResponse)
def update_user_status(user_id: UUID, data: UserStatusUpdate, db: Session = Depends(get_db), current_user=Depends(require_role("admin", "superadmin"))):
    return users_service.update_user_status(db, user_id, data, current_user)


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: UUID, db: Session = Depends(get_db), current_user=Depends(require_role("admin", "superadmin"))):
    users_service.delete_user(db, user_id, current_user)