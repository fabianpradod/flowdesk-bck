from datetime import date
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.api.dependencies.auth import get_current_user, get_db
from app.models.users import User
from app.schemas.analytics import InventoryRiskDistributionResponse, SalesCustomerType, SalesMetricsResponse, SalesTrendResponse
from app.schemas.inventory import AnalyticsPeriod, AnalyticsWindow
from app.services import analytics as analytics_service

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])

@router.get(
    "/sales/metrics",
    response_model=SalesMetricsResponse,
    summary="Métricas de ventas",
    description="Resume ventas finalizadas, importes y tipo de cliente dentro de un periodo.",
)
def sales_metrics(
    period: AnalyticsPeriod = Query(default="30d"),
    customer_type: SalesCustomerType = Query(default="all"),
    client_id: UUID | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return analytics_service.get_sales_metrics(
        current_user,
        db,
        period=period,
        customer_type=customer_type,
        client_id=client_id,
        start_date=start_date,
        end_date=end_date,
    )

@router.get(
    "/sales/trend",
    response_model=SalesTrendResponse,
    summary="Tendencia de ventas",
    description="Agrupa ventas finalizadas por día, semana o mes.",
)
def sales_trend(
    period: AnalyticsPeriod = Query(default="30d"),
    window: AnalyticsWindow = Query(default="day"),
    customer_type: SalesCustomerType = Query(default="all"),
    client_id: UUID | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return analytics_service.get_sales_trend(
        current_user,
        db,
        period=period,
        window=window,
        customer_type=customer_type,
        client_id=client_id,
        start_date=start_date,
        end_date=end_date,
    )

@router.get(
    "/inventory/risk-distribution",
    response_model=InventoryRiskDistributionResponse,
    summary="Distribución de riesgo de inventario",
    description="Clasifica productos activos por nivel de riesgo usando stock mínimo y demanda por ventas.",
)
def inventory_risk_distribution(
    period: AnalyticsPeriod = Query(default="30d"),
    supplier_id: UUID | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return analytics_service.get_inventory_risk_distribution(
        current_user,
        db,
        period=period,
        supplier_id=supplier_id,
        start_date=start_date,
        end_date=end_date,
    )