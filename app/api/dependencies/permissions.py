from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.schemas.users import AssignPermissions
from app.queries.permission_queries import get_permissions_by_names
from app.queries.user_queries import assign_permissions
from app.services.auth import require_role

router = APIRouter(prefix="/permissions", tags=["Permissions"])

#Endpoint de asignar permisos a usuario
@router.post("/assign/{user_id}")
def assign_permissions_to_user(
    user_id: int,
    data: AssignPermissions,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("admin"))
):
    user = db.query(User).filter(User.id == user_id).first()
    permissions = get_permissions_by_names(db, data.permissions)
    return assign_permissions(db, user, permissions)