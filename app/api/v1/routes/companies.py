from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import app.services.companies as companies_service
from app.api.dependencies.auth import get_current_user, get_db
from app.models.users import User
from app.schemas.companies import CompanyResponse


router = APIRouter(prefix="/api/v1/companies", tags=["companies"])


@router.get("", response_model=list[CompanyResponse], summary="Listar empresas")
def companies(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retorna las empresas al superadministrador autenticado."""
    return companies_service.list_companies(db, current_user)
