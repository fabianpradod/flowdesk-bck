import app.services.inventory as inventory_service

from datetime import date
from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session
from uuid import UUID

from app.api.dependencies.auth import get_current_user, get_db, require_role
from app.models.users import User
from app.schemas.inventory import (
    AnalyticsPeriod,
    AnalyticsWindow,
    InventoryAlertResponse,
    InventoryHistoryRow,
    InventoryMetricsResponse,
    InventoryMonthlyAnalyticsResponse,
    InventoryMovementCreate,
    InventoryMovementResponse,
    MovementType,
    InventoryTrendAnalyticsResponse,
    ProductAnalyticsResponse,
    ProductAnalyticsSort,
    ProductCreate,
    ProductImportResponse,
    ProductResponse,
    ProductStatusUpdate,
    SupplierCreate,
    SupplierResponse,
)

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])


@router.get("/suppliers", response_model=list[SupplierResponse], summary="Listar proveedores")
def suppliers(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role()),
):
    """Retorna todos los proveedores del esquema de la empresa autenticada."""
    return inventory_service.list_suppliers(current_user, db)


@router.post("/suppliers", response_model=SupplierResponse, summary="Crear proveedor")
def create_supplier(
    data: SupplierCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("manager")),
):
    """Crea un nuevo proveedor en el esquema de la empresa autenticada. Requiere rol manager o superior."""
    return inventory_service.create_supplier(data, current_user, db)


@router.get("/products", response_model=list[ProductResponse], summary="Listar productos")
def products(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role()),
):
    """Retorna todos los productos del esquema de la empresa autenticada."""
    return inventory_service.list_products(current_user, db)


@router.post("/products", response_model=ProductResponse, summary="Crear producto")
def create_product(
    data: ProductCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("manager")),
):
    """Crea un nuevo producto en el esquema de la empresa autenticada. El SKU se normaliza a minúsculas. Requiere rol manager o superior."""
    return inventory_service.create_product(data, current_user, db)


@router.patch("/products/{product_id}/status", response_model=ProductResponse, summary="Actualizar estado de producto")
def update_product_status(
    product_id: UUID,
    data: ProductStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Activa o desactiva un producto. Requiere rol admin o superior."""
    return inventory_service.update_product_status(current_user, db, product_id, data.is_active)


@router.post("/products/import", response_model=ProductImportResponse, summary="Importar productos")
def import_products(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Importa productos desde un archivo .xlsx. Máximo 5MB. Columnas requeridas: SKU, Nombre, Stock Actual, Stock Mínimo, Precio Estandar, Proveedor, Descripción, Estado."""
    return inventory_service.import_products_from_excel(current_user, db, file)


@router.get("/movements", response_model=list[InventoryMovementResponse], summary="Listar movimientos")
def movements(
    product_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role()),
):
    """Retorna los movimientos de inventario de la empresa. Filtrable por producto con ?product_id=."""
    return inventory_service.list_inventory_movements(current_user, db, product_id)


@router.post("/movements", response_model=InventoryMovementResponse, summary="Crear movimiento")
def create_movement(
    data: InventoryMovementCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("manager")),
):
    """Registra un movimiento de inventario y actualiza el stock. Dispara lógica de alertas automáticamente. Requiere rol manager o superior."""
    return inventory_service.create_inventory_movement(data, current_user, db)


@router.get("/alerts", response_model=list[InventoryAlertResponse], summary="Listar alertas")
def alerts(
    open_only: bool = Query(default=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role()),
):
    """Retorna las alertas de inventario de la empresa. Por defecto solo muestra alertas abiertas. Usar ?open_only=false para ver todas."""
    return inventory_service.list_inventory_alerts(current_user, db, open_only=open_only)


@router.get("/analytics/monthly", response_model=InventoryMonthlyAnalyticsResponse, summary="Análisis mensual")
def monthly_analytics(
    period: AnalyticsPeriod = Query(default="6m"),
    product_id: UUID | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retorna comparativa mensual de movimientos de inventario contra el período anterior."""
    return inventory_service.get_monthly_behavior(
        current_user,
        db,
        period=period,
        product_id=product_id,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("/analytics/trend", response_model=InventoryTrendAnalyticsResponse, summary="Tendencia de inventario")
def inventory_trend(
    period: AnalyticsPeriod = Query(default="30d"),
    window: AnalyticsWindow = Query(default="day"),
    product_id: UUID | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retorna la tendencia de movimientos de inventario agrupada por día, semana o mes."""
    return inventory_service.get_inventory_trend(
        current_user,
        db,
        period=period,
        window=window,
        product_id=product_id,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("/analytics/products", response_model=ProductAnalyticsResponse, summary="Análisis por producto")
def product_analytics(
    period: AnalyticsPeriod = Query(default="30d"),
    sort_by: ProductAnalyticsSort = Query(default="outbound"),
    limit: int = Query(default=10, ge=1, le=50),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retorna métricas por producto. Ordenable por entradas, salidas o stock. Límite configurable entre 1 y 50 productos."""
    return inventory_service.get_product_analytics(
        current_user,
        db,
        period=period,
        sort_by=sort_by,
        limit=limit,
        start_date=start_date,
        end_date=end_date,
    )

@router.get("/metrics", response_model=InventoryMetricsResponse)
def inventory_metrics(
    period: AnalyticsPeriod = Query(default="30d"),
    product_id: UUID | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return inventory_service.get_inventory_metrics(
        current_user,
        db,
        period=period,
        product_id=product_id,
        start_date=start_date,
        end_date=end_date,
    )

@router.get("/history", response_model=list[InventoryHistoryRow])
def inventory_history(
    limit: int = Query(default=20, ge=1, le=100),
    product_id: UUID | None = Query(default=None),
    movement_type: MovementType | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return inventory_service.list_inventory_history(
        current_user,
        db,
        limit=limit,
        product_id=product_id,
        movement_type=movement_type,
    )
