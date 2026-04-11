from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import engine
import app.services.auth as auth_service
from app.api.dependencies.auth import get_db, require_role
from app.schemas.companies import CompanyCreate, CompanyResponse
from app.schemas.users import UserCreate, UserResponse, UserLogin, PasswordSet

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

@router.post("/register", response_model=CompanyResponse)
def register(data: CompanyCreate, db: Session = Depends(get_db)):
    return auth_service.register_company(data, db, engine)

@router.post("/login")
def login(data: UserLogin, db: Session = Depends(get_db)):
    return auth_service.login(data.email, data.password, db)

@router.post("/set-password")
def set_password(data: PasswordSet, db: Session = Depends(get_db)):
    return auth_service.set_password(data.token, data.new_password, db)

@router.post("/employees", response_model=UserResponse)
def create_employee(
    data: UserCreate,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("admin"))
):
    return auth_service.create_employee(data, current_user, db)
