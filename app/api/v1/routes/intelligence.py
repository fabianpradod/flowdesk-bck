from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.api.dependencies.auth import get_current_user, get_db
from app.models.users import User
from app.schemas.intelligence import IntelligentAnalysisRequest, IntelligentAnalysisResponse
from app.services import intelligence as intelligence_service
from app.services.intelligence import AnalysisProvider

router = APIRouter(prefix="/api/v1/ai", tags=["ai-analysis"])

@router.post(
    "/analysis",
    response_model=IntelligentAnalysisResponse,
    summary="Generar análisis inteligente",
    description=(
        "Genera un análisis de inventario, ventas, catálogo o del negocio completo "
        "para la empresa autenticada. Acepta periodos predefinidos o un rango "
        "personalizado y filtros por producto, proveedor y cliente. Los datos se "
        "aíslan por empresa y no se envían datos personales al proveedor."
    ),
    responses={
        200: {"description": "Análisis generado correctamente"},
        400: {"description": "Periodo o rango de fechas inválido"},
        401: {"description": "Autenticación requerida"},
        403: {"description": "Usuario sin empresa activa"},
        502: {"description": "Respuesta inválida o error del proveedor"},
        503: {"description": "Proveedor de análisis no configurado"},
    },
)
def create_intelligent_analysis(
    data: IntelligentAnalysisRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    provider: AnalysisProvider = Depends(intelligence_service.get_analysis_provider),
):
    return intelligence_service.create_intelligent_analysis(
        data,
        current_user,
        db,
        provider,
    )