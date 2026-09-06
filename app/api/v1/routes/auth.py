import app.services.auth as auth_service

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from uuid import UUID

from app.models.users import User
from app.api.dependencies.auth import get_db, require_role
from app.schemas.companies import CompanyCreate, CompanyResponse
from app.schemas.auth import TokenResponse
from app.schemas.users import UserCreate, UserResponse, UserLogin, PasswordSet, PasswordReset, EmailRequest

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model = CompanyResponse, summary = "Registrar empresa", 
    description = """Crea una nueva empresa. El proceso realiza automáticamente:
        - Crea la empresa
        - Crea el usuario administrador
        - Genera el schema del tenant
        - Envía el correo para configurar contraseña
    """,
    responses = {
        201: {"description": "Empresa creada"},
        400: {"description": "Email o username ya registrado"},
        500: {"description": "Error interno"},
    },
    status_code = 201,
)
def create_company(data: CompanyCreate, db: Session = Depends(get_db)):
    """Crea una nueva empresa junto con su usuario administrador y su esquema de base de datos. Solo accesible para superadmin."""
    return auth_service.register_company(data, db)


@router.post("/login", response_model = TokenResponse, summary = "Iniciar sesión", 
    description = """Autentica un usuario activo. Devuelve un JWT con:
        - id usuario
        - rol
        - company_id
        - schema_name
    """,
    responses = {
        200: {"description": "Login correcto"},
        401: {"description": "Credenciales inválidas"},
        403: {"description": "Usuario inactivo"},
    },
)
def login(data: UserLogin, db: Session = Depends(get_db)):
    """Autentica al usuario y retorna un JWT con su rol, empresa y esquema."""
    return auth_service.login(data.email, data.password, db)


@router.post("/password/set", summary = "Configurar contraseña",
    description = """Permite establecer la contraseña inicial utilizando el token enviado por correo.""",
    responses = {
        200: {"description": "Contraseña configurada"},
        400: {"description": "Token inválido"},
        404: {"description": "Usuario inexistente"},
    },
)
def set_password(data: PasswordSet, db: Session = Depends(get_db)):
    """Establece la contraseña inicial de un usuario usando el token enviado por correo. Activa la cuenta."""
    return auth_service.set_password(data.token, data.new_password, db)


@router.post("/employees", response_model=UserResponse, summary = """"Crea un nuevo usuario.
        Admin:
            - Solo puede crear empleados en su empresa.
-
        Superadmin:
            - Puede crear empleados para cualquier empresa indicando company_id.
    """,
    responses = {
        201: {"description": "Empleado creado"},
        400: {"description": "Datos inválidos"},
        403: {"description": "Sin permisos"},
        404: {"description": "Rol o empresa inexistente"},
    },
    status_code = 201,
)
def create_employee(data: UserCreate, db: Session = Depends(get_db), current_user: User = Depends(require_role("admin"))):
    """Crea un nuevo empleado en la empresa del admin autenticado y envía una invitación por correo."""
    return auth_service.create_employee(data, current_user, db)


@router.post("/invitations/resend", summary = "Reenviar invitación", 
    description = """Reenvía el correo de invitación a un usuario pendiente de activación.""",
    responses = {
        200: {"description": "Invitación reenviada"},
        400: {"description": "Usuario activo"},
        404: {"description": "Usuario no encontrado"},
    }
)
def resend_invitation(data: EmailRequest, db: Session = Depends(get_db), current_user: User = Depends(require_role("admin"))):
    """Reenvía el correo de invitación a un empleado que aún no ha activado su cuenta."""
    return auth_service.resend_invitation(data.email, current_user, db)


@router.post("/password/forgot", summary = "Solicitar recuperación",
    description = """Envía un correo con un enlace para recuperar la contraseña. Máximo:
        - 3 solicitudes
        - por 24 horas
    """,
    responses = {
        200: {"description": "Solicitud procesada"},
        429: {"description": "Demasiadas solicitudes"},
    },
)
def forgot_password(data: EmailRequest, db: Session = Depends(get_db)):
    """Envía un correo con un token para restablecer la contraseña. Máximo 3 solicitudes por 24 horas."""
    return auth_service.forgot_password(data.email, db)


@router.post("/password/reset", summary = "Restablecer contraseña",
    description = """Actualiza la contraseña utilizando el token recibido por correo.""",
    responses = {
        200: {"description": "Contraseña actualizada"},
        400: {"description": "Token inválido"},
        403: {"description": "Cuenta inactiva"},
    },
)
def reset_password(data: PasswordReset, db: Session = Depends(get_db)):
    """Restablece la contraseña usando el token enviado por correo."""
    return auth_service.reset_password(data.token, data.new_password, db)

@router.get("/employees", response_model = list[UserResponse], summary = "Listar empleados",
    description = """Lista los empleados.
        - Admin: únicamente su empresa
        - Superadmin: todas las empresas
    """,
    responses = {
        200: {"description": "Listado obtenido"},
        403: {"description": "Sin permisos"},
    },
)
def employees(db: Session = Depends(get_db), current_user: User = Depends(require_role("admin"))):
    """Retorna los empleados de la empresa del admin autenticado."""
    return auth_service.list_employees(current_user, db)
