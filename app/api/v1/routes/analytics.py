from datetime import date
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.api.dependencies.auth import get_current_user, get_db
from app.models.users import User
from app.schemas.analytics import InventoryRiskDistributionResponse, ProductCreationTrendResponse, SalesCustomerType, SalesMetricsResponse, SalesTrendResponse, TopSellingProductsResponse
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

@router.get(
    "/sales/top-products",
    response_model=TopSellingProductsResponse,
    summary="Top de productos vendidos",
    description=(
        "Ordena productos por unidades vendidas en ventas finalizadas. "
        "Permite filtrar por cliente, tipo de cliente, proveedor, producto y periodo."
    ),
)
def top_selling_products(
    period: AnalyticsPeriod = Query(default="30d"),
    customer_type: SalesCustomerType = Query(default="all"),
    client_id: UUID | None = Query(default=None),
    supplier_id: UUID | None = Query(default=None),
    product_id: UUID | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return analytics_service.get_top_selling_products(
        current_user,
        db,
        period=period,
        customer_type=customer_type,
        client_id=client_id,
        supplier_id=supplier_id,
        product_id=product_id,
        limit=limit,
        start_date=start_date,
        end_date=end_date,
    )

@router.get(
    "/catalog/product-creation-trend",
    response_model=ProductCreationTrendResponse,
    summary="Tendencia de creación de productos",
    description=(
        "Agrupa los productos creados por día, semana o mes y separa los activos "
        "de los inactivos. Permite filtrar por proveedor, estado y periodo."
    ),
)
def product_creation_trend(
    period: AnalyticsPeriod = Query(default="30d"),
    window: AnalyticsWindow = Query(default="day"),
    supplier_id: UUID | None = Query(default=None),
    active_only: bool | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return analytics_service.get_product_creation_trend(
        current_user,
        db,
        period=period,
        window=window,
        supplier_id=supplier_id,
        active_only=active_only,
        start_date=start_date,
        end_date=end_date,
    )