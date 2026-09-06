from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from uuid import UUID
from app.api.dependencies.auth import get_db, get_current_user, require_role
from app.schemas.users import UserResponse, UserUpdate, UserStatusUpdate
import app.services.users as users_service

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("", response_model = list[UserResponse], summary = "Listar usuarios",
    description = """
        Admin:
            - únicamente usuarios de su empresa
        Superadmin:
            - todos los usuarios
    """,
    responses = {
        200: {"description": "Usuarios obtenidos"},
        403: {"description": "Sin permisos"},
    },
)
def users(db: Session = Depends(get_db), current_user=Depends(require_role("admin"))):
    """Retorna todos los usuarios. El admin solo ve los usuarios de su empresa, el superadmin ve todos."""
    return users_service.get_users(db, current_user)


@router.put("/{user_id}", response_model = UserResponse, summary = "Actualizar usuario",
    description = """Actualiza el username y/o rol de un usuario. El admin solo puede modificar usuarios de su propia empresa.""",
    responses = {
        200: {"description": "Usuario actualizado"},
        400: {"description": "Datos inválidos"},
        403: {"description": "Sin permisos"},
        404: {"description": "Usuario no encontrado"},
    },
)
def update_user(user_id: UUID, data: UserUpdate, db: Session = Depends(get_db), current_user=Depends(require_role("admin"))):
    """Actualiza el username y/o rol de un usuario. El admin solo puede modificar usuarios de su propia empresa."""
    return users_service.update_user(db, user_id, data, current_user)


@router.patch("/{user_id}/status", response_model = UserResponse, summary = "Actualizar estado de usuario",
    description = """Activa o desactiva un usuario. El admin solo puede modificar usuarios de su propia empresa.""",
    responses = {
        200: {"description": "Estado de usuario actualizado"},
        403: {"description": "Sin permisos"},
        404: {"description": "Usuario no encontrado"},
    },
)
def update_user_status(user_id: UUID, data: UserStatusUpdate, db: Session = Depends(get_db), current_user=Depends(require_role("admin"))):
    """Activa o desactiva un usuario. El admin solo puede modificar usuarios de su propia empresa."""
    return users_service.update_user_status(db, user_id, data, current_user)


@router.delete("/{user_id}", status_code = 204, summary = "Eliminar usuario",
    description = """Desactiva un usuario sin eliminar el registro. El admin solo puede afectar usuarios de su propia empresa.""",
    responses = {
        204: {"description": "Usuario desactivado"},
        403: {"description": "Sin permisos"},
        404: {"description": "Usuario no encontrado"},
    },
)
def delete_user(user_id: UUID, db: Session = Depends(get_db), current_user=Depends(require_role("admin"))):
    """Soft delete — desactiva el usuario sin eliminar el registro. El admin solo puede afectar usuarios de su propia empresa."""
    users_service.delete_user(db, user_id, current_user)