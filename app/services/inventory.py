from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from app.models.users import User
from app.schemas.inventory import (
    InventoryMovementCreate,
    ProductCreate,
    SupplierCreate,
)
from app.tenancy.runtime import get_tenant_tables, get_user_schema_name
from app.utils.exceptions import AppError


INBOUND_MOVEMENTS = {
    "entrada_compra",
    "entrada_manual",
    "ajuste_positivo",
    "devolucion_cliente",
}
OUTBOUND_MOVEMENTS = {
    "salida_venta",
    "salida_manual",
    "ajuste_negativo",
    "devolucion_proveedor",
}
OPEN_ALERT_STATUS = "pendiente"
LOW_STOCK_ALERT_TYPES = {"stock_bajo", "sin_stock"}


def list_suppliers(current_user: User, db: Session) -> list[dict]:
    tables = _get_tenant_tables_for_user(current_user)
    suppliers = tables["proveedor"]
    rows = db.execute(
        select(suppliers).order_by(suppliers.c.nombre.asc())
    ).mappings()
    return [dict(row) for row in rows]


def create_supplier(data: SupplierCreate, current_user: User, db: Session) -> dict:
    tables = _get_tenant_tables_for_user(current_user)
    suppliers = tables["proveedor"]
    now = _utcnow()
    supplier_id = uuid4()
    db.execute(
        insert(suppliers).values(
            id=supplier_id,
            nombre=data.nombre.strip(),
            telefono=data.telefono,
            correo=data.correo,
            direccion=data.direccion,
            updated_at=now,
        )
    )
    db.commit()
    row = db.execute(
        select(suppliers).where(suppliers.c.id == supplier_id)
    ).mappings().one()
    return dict(row)


def list_products(current_user: User, db: Session) -> list[dict]:
    tables = _get_tenant_tables_for_user(current_user)
    products = tables["producto"]
    rows = db.execute(
        select(products).order_by(products.c.nombre.asc())
    ).mappings()
    return [dict(row) for row in rows]


def create_product(data: ProductCreate, current_user: User, db: Session) -> dict:
    tables = _get_tenant_tables_for_user(current_user)
    products = tables["producto"]
    suppliers = tables["proveedor"]

    sku = data.sku.strip().lower()

    if data.proveedor_id:
        supplier = db.execute(
            select(suppliers.c.id, suppliers.c.is_active).where(suppliers.c.id == data.proveedor_id)
        ).mappings().first()
        if supplier is None:
            raise AppError(status_code=404, message="Supplier not found")
        if not supplier["is_active"]:
            raise AppError(status_code=400, message="Supplier is inactive")

    existing = db.execute(
        select(products.c.id).where(products.c.sku == sku)
    ).first()
    if existing:
        raise AppError(status_code=400, message="SKU already exists")

    now = _utcnow()
    product_id = uuid4()
    db.execute(
        insert(products).values(
            id=product_id,
            proveedor_id=data.proveedor_id,
            sku=sku,
            nombre=data.nombre.strip(),
            descripcion=data.descripcion,
            precio_venta=data.precio_venta,
            stock_minimo=data.stock_minimo,
            unidad_medida=data.unidad_medida.strip(),
            updated_at=now,
        )
    )
    db.commit()
    row = db.execute(
        select(products).where(products.c.id == product_id)
    ).mappings().one()
    return dict(row)


def list_inventory_movements(current_user: User, db: Session, product_id=None) -> list[dict]:
    tables = _get_tenant_tables_for_user(current_user)
    movements = tables["movimiento_inventario"]
    query = select(movements).order_by(movements.c.fecha.desc())
    if product_id is not None:
        query = query.where(movements.c.producto_id == product_id)
    rows = db.execute(query).mappings()
    return [dict(row) for row in rows]


def create_inventory_movement(data: InventoryMovementCreate, current_user: User, db: Session) -> dict:
    tables = _get_tenant_tables_for_user(current_user)
    products = tables["producto"]
    movements = tables["movimiento_inventario"]
    alerts = tables["alerta"] 

    product = db.execute(
        select(products).where(products.c.id == data.producto_id).with_for_update()
    ).mappings().first()
    if product is None:
        raise AppError(status_code=404, message="Product not found")
    if not product["is_active"]:
        raise AppError(status_code=400, message="Product is inactive")

    direction = _movement_direction(data.tipo_movimiento)
    stock_anterior = _to_decimal(product["stock_actual"])
    cantidad = _to_decimal(data.cantidad)

    if cantidad <= 0:
        raise AppError(status_code=400, message="Quantity must be greater than zero")

    delta = cantidad if direction == "in" else -cantidad
    stock_resultante = stock_anterior + delta
    if stock_resultante < Decimal("0"):
        raise AppError(status_code=400, message="Insufficient stock for this movement")
    
    now = _utcnow()
    movement_id = uuid4()

    try:
        db.execute(
            update(products)
            .where(products.c.id == data.producto_id)
            .values(stock_actual=stock_resultante, updated_at=now)
        )
        db.execute(
            insert(movements).values(
                id=movement_id,
                producto_id=data.producto_id,
                usuario_id=current_user.id,
                tipo_movimiento=data.tipo_movimiento,
                fecha=now,
                cantidad=cantidad,
                stock_anterior=stock_anterior,
                stock_resultante=stock_resultante,
                motivo=data.motivo,
                referencia_tipo=data.referencia_tipo,
                referencia_id=data.referencia_id,
            )
        )
        _sync_stock_alerts(
            db=db,
            alerts=alerts,
            product_id=data.producto_id,
            product_name=product["nombre"],
            stock_resultante=stock_resultante,
            stock_minimo=_to_decimal(product["stock_minimo"]),
            now=now,
        )
        db.commit()
    except Exception as e:
        db.rollback()
        raise AppError(500, f"Inventory movement failed: {str(e)}")

    row = db.execute(
        select(movements).where(movements.c.id == movement_id)
    ).mappings().one()
    return dict(row)


def list_inventory_alerts(current_user: User, db: Session, open_only: bool = True) -> list[dict]:
    tables = _get_tenant_tables_for_user(current_user)
    alerts = tables["alerta"]
    query = select(alerts).order_by(alerts.c.fecha.desc())
    if open_only:
        query = query.where(alerts.c.estado == OPEN_ALERT_STATUS)
    rows = db.execute(query).mappings()
    return [dict(row) for row in rows]


def _get_tenant_tables_for_user(current_user: User) -> dict:
    schema_name = get_user_schema_name(current_user)
    return get_tenant_tables(schema_name)


def _movement_direction(movement_type: str) -> str:
    if movement_type in INBOUND_MOVEMENTS:
        return "in"
    if movement_type in OUTBOUND_MOVEMENTS:
        return "out"
    raise AppError(status_code=400, message="Unsupported inventory movement type")


def _sync_stock_alerts(
    *,
    db: Session,
    alerts,
    product_id,
    product_name: str,
    stock_resultante: Decimal,
    stock_minimo: Decimal,
    now: datetime,
) -> None:
    open_alert_rows = db.execute(
        select(alerts).where(
            alerts.c.producto_id == product_id,
            alerts.c.estado == OPEN_ALERT_STATUS,
            alerts.c.tipo.in_(LOW_STOCK_ALERT_TYPES),
        )
    ).mappings().all()

    desired_type = None
    desired_message = None
    if stock_resultante <= Decimal("0"):
        desired_type = "sin_stock"
        desired_message = f"El producto '{product_name}' no tiene stock disponible."
    elif stock_resultante <= stock_minimo:
        desired_type = "stock_bajo"
        desired_message = (
            f"El producto '{product_name}' alcanzó stock bajo "
            f"({stock_resultante} <= {stock_minimo})."
        )

    for alert in open_alert_rows:
        if alert["tipo"] != desired_type:
            db.execute(
                update(alerts)
                .where(alerts.c.id == alert["id"])
                .values(estado="resuelta", resuelta_en=now)
            )

    if desired_type is None:
        return

    already_open = any(alert["tipo"] == desired_type for alert in open_alert_rows)
    if not already_open:
        db.execute(
            insert(alerts).values(
                id=uuid4(),
                producto_id=product_id,
                tipo=desired_type,
                mensaje=desired_message,
                fecha=now,
                estado=OPEN_ALERT_STATUS,
                resuelta_en=None,
            )
        )


def _to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
