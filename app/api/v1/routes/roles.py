from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.api.dependencies.auth import get_db, require_role
from app.models.roles import Role
from app.schemas.roles import RoleResponse

router = APIRouter(prefix="/api/v1/roles", tags=["roles"])


@router.get("", response_model=list[RoleResponse], summary="Listar roles",
    description="""Obtiene todos los roles disponibles. Solo accesible para administradores.""",
    responses={
        200: {"description": "Listado de roles"},
        403: {"description": "Sin permisos"},
    }
)
def roles(db: Session = Depends(get_db), current_user=Depends(require_role("admin", "superadmin"))):
    """Retorna todos los roles disponibles en el sistema. Solo accesible para administradores y superadmin."""
    return db.query(Role).all()