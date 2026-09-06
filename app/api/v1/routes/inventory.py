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
    SupplierStatusUpdate,
    SupplierUpdate,
    SupplierProductResponse,
)

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])


@router.get("/suppliers", response_model=list[SupplierResponse], summary="Listar proveedores", 
            description =
                "Retorna los proveedores del esquema de la empresa autenticada. Filtrable por nombre con ?search= y por estado con ?is_active=."
)
def suppliers(
    search: str | None = Query(default=None, max_length=100),
    is_active: bool | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role()),
):
    return inventory_service.list_suppliers(current_user, db, search=search, is_active=is_active)


@router.post("/suppliers", response_model=SupplierResponse, summary="Crear proveedor", 
            description =
                "Crea un nuevo proveedor en el esquema de la empresa autenticada. El nombre no puede repetir el de otro proveedor activo. " \
                "Requiere rol manager o superior."
)
def create_supplier(
    data: SupplierCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("manager")),
):
    return inventory_service.create_supplier(data, current_user, db)


@router.get("/suppliers/{supplier_id}", response_model=SupplierResponse, summary="Obtener proveedor", 
            description =
                "Retorna un proveedor por su id."
)
def supplier(
    supplier_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role()),
):
    return inventory_service.get_supplier(current_user, db, supplier_id)


@router.put("/suppliers/{supplier_id}", response_model=SupplierResponse, summary="Actualizar proveedor", 
            description =
                "Actualiza los datos de un proveedor. Solo se modifican los campos enviados. Requiere rol manager o superior."
)
def update_supplier(
    supplier_id: UUID,
    data: SupplierUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("manager")),
):
    return inventory_service.update_supplier(data, current_user, db, supplier_id)


@router.patch("/suppliers/{supplier_id}/status", response_model=SupplierResponse, summary="Actualizar estado de proveedor", 
            description =
                "Activa o desactiva un proveedor. No se puede desactivar si aún tiene productos activos asociados. Requiere rol admin o superior."
)
def update_supplier_status(
    supplier_id: UUID,
    data: SupplierStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return inventory_service.update_supplier_status(current_user, db, supplier_id, data.is_active)


@router.delete("/suppliers/{supplier_id}", status_code=204, summary="Eliminar proveedor", 
            description =
                "Soft delete — desactiva el proveedor sin eliminar el registro. No se puede eliminar si aún tiene productos activos asociados. " \
                "Requiere rol admin o superior."
)
def delete_supplier(
    supplier_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    inventory_service.delete_supplier(current_user, db, supplier_id)


@router.get("/products", response_model=list[ProductResponse], summary="Listar productos", 
            description =
                "Retorna todos los productos del esquema de la empresa autenticada."
)
def products(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role()),
):
    return inventory_service.list_products(current_user, db)


@router.post("/products", response_model=ProductResponse, summary="Crear producto", 
            description =
                "Crea un nuevo producto en el esquema de la empresa autenticada. El SKU se normaliza a minúsculas. Requiere rol manager o superior."
)
def create_product(
    data: ProductCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("manager")),
):
    return inventory_service.create_product(data, current_user, db)


@router.patch("/products/{product_id}/status", response_model=ProductResponse, summary="Actualizar estado de producto", 
            description =
                "Activa o desactiva un producto. Requiere rol admin o superior."
)
def update_product_status(
    product_id: UUID,
    data: ProductStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return inventory_service.update_product_status(current_user, db, product_id, data.is_active)


@router.post("/products/import", response_model=ProductImportResponse, summary="Importar productos", 
            description =
                "Importa productos desde un archivo .xlsx. Máximo 5MB. Columnas requeridas: SKU, Nombre, Stock Actual, " \
                "Stock Mínimo, Precio Estandar, Proveedor, Descripción, Estado."
)
def import_products(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("manager")),
):
    return inventory_service.import_products_from_file(file.filename or "", file.file.read(), current_user, db)


@router.get("/movements", response_model=list[InventoryMovementResponse], summary="Listar movimientos", 
            description =
                "Retorna los movimientos de inventario de la empresa. Filtrable por producto con ?product_id=."
)
def movements(
    product_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role()),
):
    return inventory_service.list_inventory_movements(current_user, db, product_id)


@router.post("/movements", response_model=InventoryMovementResponse, summary="Crear movimiento", 
            description =
                "Registra un movimiento de inventario y actualiza el stock. Dispara lógica de alertas automáticamente. Requiere rol manager o superior."
)
def create_movement(
    data: InventoryMovementCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("manager")),
):
    return inventory_service.create_inventory_movement(data, current_user, db)


@router.get("/alerts", response_model=list[InventoryAlertResponse], summary="Listar alertas", 
            description =
                "Retorna las alertas de inventario de la empresa. Por defecto solo muestra alertas abiertas. Usar ?open_only=false para ver todas."
)
def alerts(
    open_only: bool = Query(default=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role()),
):
    return inventory_service.list_inventory_alerts(current_user, db, open_only=open_only)


@router.get("/analytics/monthly", response_model=InventoryMonthlyAnalyticsResponse, summary="Análisis mensual", 
            description =
                "Retorna comparativa mensual de movimientos de inventario contra el período anterior."
)
def monthly_analytics(
    period: AnalyticsPeriod = Query(default="6m"),
    product_id: UUID | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return inventory_service.get_monthly_behavior(
        current_user,
        db,
        period=period,
        product_id=product_id,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("/analytics/trend", response_model=InventoryTrendAnalyticsResponse, summary="Tendencia de inventario", 
            description =
                "Retorna la tendencia de movimientos de inventario agrupada por día, semana o mes."
)
def inventory_trend(
    period: AnalyticsPeriod = Query(default="30d"),
    window: AnalyticsWindow = Query(default="day"),
    product_id: UUID | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return inventory_service.get_inventory_trend(
        current_user,
        db,
        period=period,
        window=window,
        product_id=product_id,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("/analytics/products", response_model = ProductAnalyticsResponse, summary = "Análisis por producto", 
            description =
                "Retorna métricas por producto. Ordenable por entradas, salidas o stock. Límite configurable entre 1 y 50 productos."
)
def product_analytics(
    period: AnalyticsPeriod = Query(default="30d"),
    sort_by: ProductAnalyticsSort = Query(default="outbound"),
    limit: int = Query(default=10, ge=1, le=50),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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

@router.get("/supplier-products", response_model = list[SupplierProductResponse], summary = "Consultar proveedores por producto", 
            description =
                "Retorna los proveedores que ofrecen determinados productos, incluyendo cotización y descripción. Filtrable por producto " \
                "con ?product_id= y por proveedor con ?supplier_id=. También se puede buscar por nombre de proveedor o producto con ?search=. " \
                "Por defecto solo muestra proveedores activos, usar ?active_only=false para ver todos."
)
def list_supplier_products(
    product_id: UUID | None = Query(default=None),
    supplier_id: UUID | None = Query(default=None),
    search: str | None = Query(default=None),
    active_only: bool = Query(default=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role()),
):
    return inventory_service.list_supplier_products(
        current_user,
        db,
        producto_id=product_id,
        proveedor_id=supplier_id,
        search=search,
        active_only=active_only,
    )
