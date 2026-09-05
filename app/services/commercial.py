from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, insert, or_, select, update
from sqlalchemy.orm import Session

from app.schemas.commercial import ClientCreate, ClientUpdate, SaleCreate
from app.services.inventory import _sync_stock_alerts
from app.tenancy.runtime import get_tenant_tables, get_user_schema_name
from app.utils.exceptions import AppError


def list_clients(
    current_user,
    db: Session,
    *,
    search: str | None = None,
    active_only: bool = True,
) -> list[dict]:
    clients = _clients_table(current_user)
    query = select(clients).order_by(clients.c.nombre.asc())
    if active_only:
        query = query.where(clients.c.is_active.is_(True))
    if search:
        term = f"%{search.strip().lower()}%"
        query = query.where(
            or_(
                func.lower(clients.c.nombre).like(term),
                func.lower(clients.c.correo).like(term),
                func.lower(clients.c.telefono).like(term),
            )
        )
    rows = db.execute(query).mappings()
    return [dict(row) for row in rows]


def get_client(client_id: UUID, current_user, db: Session) -> dict:
    clients = _clients_table(current_user)
    row = db.execute(select(clients).where(clients.c.id == client_id)).mappings().first()
    if row is None:
        raise AppError(status_code=404, message="Client not found")
    return dict(row)


def create_client(data: ClientCreate, current_user, db: Session) -> dict:
    clients = _clients_table(current_user)
    payload = _client_payload(data)
    _ensure_email_available(db, clients, payload.get("correo"))

    now = _utcnow()
    client_id = uuid4()
    try:
        db.execute(
            insert(clients).values(
                id=client_id,
                **payload,
                updated_at=now,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return get_client(client_id, current_user, db)


def update_client(client_id: UUID, data: ClientUpdate, current_user, db: Session) -> dict:
    clients = _clients_table(current_user)
    _ensure_client_exists(db, clients, client_id)
    payload = _client_payload(data, exclude_unset=True)
    if not payload:
        raise AppError(status_code=400, message="At least one field must be provided")

    if "correo" in payload:
        _ensure_email_available(db, clients, payload.get("correo"), exclude_client_id=client_id)

    try:
        db.execute(
            update(clients)
            .where(clients.c.id == client_id)
            .values(**payload, updated_at=_utcnow())
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return get_client(client_id, current_user, db)


def update_client_status(client_id: UUID, is_active: bool, current_user, db: Session) -> dict:
    clients = _clients_table(current_user)
    _ensure_client_exists(db, clients, client_id)
    try:
        db.execute(
            update(clients)
            .where(clients.c.id == client_id)
            .values(is_active=is_active, updated_at=_utcnow())
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return get_client(client_id, current_user, db)


def delete_client(client_id: UUID, current_user, db: Session) -> None:
    clients = _clients_table(current_user)
    _ensure_client_exists(db, clients, client_id)
    try:
        db.execute(
            update(clients)
            .where(clients.c.id == client_id)
            .values(is_active=False, updated_at=_utcnow())
        )
        db.commit()
    except Exception:
        db.rollback()
        raise


def create_sale(data: SaleCreate, current_user, db: Session) -> dict:
    """Register a sale and its stock movements as one atomic transaction."""
    tables = _tenant_tables(current_user)
    clients = tables["cliente"]
    products = tables["producto"]
    sales = tables["venta"]
    sale_items = tables["detalle_venta"]
    movements = tables["movimiento_inventario"]
    alerts = tables["alerta"]

    client_name = None
    if data.cliente_id is not None:
        client = db.execute(
            select(clients).where(clients.c.id == data.cliente_id)
        ).mappings().first()
        if client is None:
            raise AppError(status_code=404, message="Client not found")
        if not client["is_active"]:
            raise AppError(status_code=400, message="Client is inactive")
        client_name = client["nombre"]

    product_ids = [item.producto_id for item in data.items]
    product_rows = db.execute(
        select(products).where(products.c.id.in_(product_ids)).with_for_update()
    ).mappings()
    products_by_id = {row["id"]: dict(row) for row in product_rows}
    missing = next((product_id for product_id in product_ids if product_id not in products_by_id), None)
    if missing is not None:
        raise AppError(status_code=404, message=f"Product not found: {missing}")

    prepared_items = []
    subtotal = Decimal("0")
    for item in data.items:
        product = products_by_id[item.producto_id]
        if not product["is_active"]:
            raise AppError(status_code=400, message=f"Product is inactive: {item.producto_id}")
        quantity = _decimal(item.cantidad)
        stock_before = _decimal(product["stock_actual"])
        stock_after = stock_before - quantity
        if stock_after < 0:
            raise AppError(status_code=400, message=f"Insufficient stock: {item.producto_id}")
        unit_price = _decimal(product["precio_venta"])
        line_subtotal = (quantity * unit_price).quantize(Decimal("0.01"))
        subtotal += line_subtotal
        prepared_items.append((item, product, quantity, stock_before, stock_after, unit_price, line_subtotal))

    discount = _decimal(data.descuento)
    tax = _decimal(data.impuesto)
    if subtotal > Decimal("99999999.99"):
        raise AppError(status_code=400, message="Sale subtotal exceeds maximum allowed value")
    if discount > subtotal:
        raise AppError(status_code=400, message="Discount cannot exceed subtotal")
    total = (subtotal - discount + tax).quantize(Decimal("0.01"))
    if total > Decimal("99999999.99"):
        raise AppError(status_code=400, message="Sale total exceeds maximum allowed value")
    now = _utcnow()
    sale_id = uuid4()

    try:
        db.execute(
            insert(sales).values(
                id=sale_id,
                usuario_id=current_user.id,
                cliente_id=data.cliente_id,
                fecha=now,
                subtotal=subtotal,
                descuento=discount,
                impuesto=tax,
                total=total,
                estado="completada",
                created_at=now,
                updated_at=now,
            )
        )
        for item, product, quantity, stock_before, stock_after, unit_price, line_subtotal in prepared_items:
            db.execute(
                insert(sale_items).values(
                    id=uuid4(),
                    venta_id=sale_id,
                    producto_id=item.producto_id,
                    cantidad=quantity,
                    precio_unitario=unit_price,
                    subtotal=line_subtotal,
                )
            )
            db.execute(
                update(products)
                .where(products.c.id == item.producto_id)
                .values(stock_actual=stock_after, updated_at=now)
            )
            db.execute(
                insert(movements).values(
                    id=uuid4(),
                    producto_id=item.producto_id,
                    usuario_id=current_user.id,
                    tipo_movimiento="salida_venta",
                    fecha=now,
                    cantidad=quantity,
                    stock_anterior=stock_before,
                    stock_resultante=stock_after,
                    motivo="Venta",
                    referencia_tipo="venta",
                    referencia_id=sale_id,
                )
            )
            _sync_stock_alerts(
                db=db,
                alerts=alerts,
                product_id=item.producto_id,
                product_name=product["nombre"],
                stock_resultante=stock_after,
                stock_minimo=_decimal(product["stock_minimo"]),
                now=now,
            )
        db.commit()
    except AppError:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise AppError(status_code=500, message="Sale registration failed") from exc

    return get_sale(sale_id, current_user, db, client_name=client_name)


def get_sale(sale_id: UUID, current_user, db: Session, *, client_name: str | None = None) -> dict:
    tables = _tenant_tables(current_user)
    sales = tables["venta"]
    clients = tables["cliente"]
    sale_items = tables["detalle_venta"]
    sale = db.execute(
        select(
            sales,
            clients.c.nombre.label("cliente_nombre"),
        )
        .select_from(sales.outerjoin(clients, sales.c.cliente_id == clients.c.id))
        .where(sales.c.id == sale_id)
    ).mappings().first()
    if sale is None:
        raise AppError(status_code=404, message="Sale not found")
    result = dict(sale)
    if client_name is not None:
        result["cliente_nombre"] = client_name
    result["consumidor_final"] = result["cliente_id"] is None
    result["items"] = [
        dict(row)
        for row in db.execute(
            select(sale_items)
            .where(sale_items.c.venta_id == sale_id)
            .order_by(sale_items.c.id.asc())
        ).mappings()
    ]
    return result


def list_client_purchases(
    client_id: UUID,
    current_user,
    db: Session,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    tables = _tenant_tables(current_user)
    clients = tables["cliente"]
    sales = tables["venta"]
    client = db.execute(select(clients).where(clients.c.id == client_id)).mappings().first()
    if client is None:
        raise AppError(status_code=404, message="Client not found")
    sale_ids = [
        row[0]
        for row in db.execute(
            select(sales.c.id)
            .where(sales.c.cliente_id == client_id)
            .order_by(sales.c.fecha.desc())
            .limit(limit)
            .offset(offset)
        )
    ]
    return [get_sale(sale_id, current_user, db, client_name=client["nombre"]) for sale_id in sale_ids]


def _clients_table(current_user):
    schema_name = get_user_schema_name(current_user)
    return get_tenant_tables(schema_name)["cliente"]


def _tenant_tables(current_user):
    schema_name = get_user_schema_name(current_user)
    return get_tenant_tables(schema_name)


def _client_payload(data, *, exclude_unset: bool = False) -> dict:
    raw = data.model_dump(exclude_unset=exclude_unset)
    payload = {}
    for key, value in raw.items():
        if value is None:
            payload[key] = None
        elif key == "correo":
            payload[key] = str(value).strip().lower()
        else:
            payload[key] = str(value).strip()
    return payload


def _ensure_email_available(db: Session, clients, correo: str | None, *, exclude_client_id: UUID | None = None) -> None:
    if not correo:
        return
    query = select(clients.c.id).where(func.lower(clients.c.correo) == correo.lower())
    if exclude_client_id is not None:
        query = query.where(clients.c.id != exclude_client_id)
    existing = db.execute(query).first()
    if existing:
        raise AppError(status_code=400, message="Client email already exists")


def _ensure_client_exists(db: Session, clients, client_id: UUID) -> None:
    existing = db.execute(select(clients.c.id).where(clients.c.id == client_id)).first()
    if not existing:
        raise AppError(status_code=404, message="Client not found")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _decimal(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))
