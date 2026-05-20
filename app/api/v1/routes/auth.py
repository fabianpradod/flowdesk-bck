import app.services.auth as auth_service

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.models.users import User
from app.api.dependencies.auth import get_db, require_role
from app.schemas.companies import CompanyCreate, CompanyResponse
from app.schemas.users import UserCreate, UserResponse, UserLogin, PasswordSet, PasswordReset, EmailRequest

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=CompanyResponse, summary="Registrar empresa")
def create_company(data: CompanyCreate, db: Session = Depends(get_db)):
    """Crea una nueva empresa junto con su usuario administrador y su esquema de base de datos. Solo accesible para superadmin."""
    return auth_service.register_company(data, db)


@router.post("/login", summary="Iniciar sesión")
def login(data: UserLogin, db: Session = Depends(get_db)):
    """Autentica al usuario y retorna un JWT con su rol, empresa y esquema."""
    return auth_service.login(data.email, data.password, db)


@router.post("/password/set", summary="Establecer contraseña")
def set_password(data: PasswordSet, db: Session = Depends(get_db)):
    """Establece la contraseña inicial de un usuario usando el token enviado por correo. Activa la cuenta."""
    return auth_service.set_password(data.token, data.new_password, db)


@router.post("/employees", response_model=UserResponse, summary="Crear empleado")
def create_employee(data: UserCreate, db: Session = Depends(get_db), current_user: User = Depends(require_role("admin"))):
    """Crea un nuevo empleado en la empresa del admin autenticado y envía una invitación por correo."""
    return auth_service.create_employee(data, current_user, db)


@router.post("/invitations/resend", summary="Reenviar invitación")
def resend_invitation(data: EmailRequest, db: Session = Depends(get_db), current_user: User = Depends(require_role("admin"))):
    """Reenvía el correo de invitación a un empleado que aún no ha activado su cuenta."""
    return auth_service.resend_invitation(data.email, current_user, db)


@router.post("/password/forgot", summary="Recuperar contraseña")
def forgot_password(data: EmailRequest, db: Session = Depends(get_db)):
    """Envía un correo con un token para restablecer la contraseña. Máximo 3 solicitudes por 24 horas."""
    return auth_service.forgot_password(data.email, db)


@router.post("/password/reset", summary="Restablecer contraseña")
def reset_password(data: PasswordReset, db: Session = Depends(get_db)):
    """Restablece la contraseña usando el token enviado por correo."""
    return auth_service.reset_password(data.token, data.new_password, db)