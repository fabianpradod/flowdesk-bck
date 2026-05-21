import csv
import re
import zipfile
from datetime import date, datetime, time, timezone, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO, StringIO
from uuid import UUID
from uuid import uuid4
from xml.etree import ElementTree

from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from app.models.users import User
from app.schemas.inventory import (
    AnalyticsPeriod,
    AnalyticsWindow,
    InventoryMovementCreate,
    MovementType,
    ProductAnalyticsSort,
    ProductCreate,
    SupplierCreate,
)
from app.tenancy.runtime import get_tenant_tables, get_user_schema_name
from app.utils.exceptions import AppError, ProductImportError
from fastapi import UploadFile
from app.utils.excel import load_excel_rows
from app.utils.logger import logger
from app.core.config import MAX_IMPORT_FILE_SIZE

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
PRODUCT_IMPORT_ALLOWED_COLUMNS = {
    "sku",
    "nombre",
    "descripcion",
    "precio_venta",
    "stock_minimo",
    "unidad_medida",
    "proveedor_id",
}
PRODUCT_IMPORT_REQUIRED_COLUMNS = {"sku", "nombre"}
PERIOD_DAYS = {
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "6m": 183,
    "12m": 366,
}


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


def import_products_from_file(filename: str, content: bytes, current_user: User, db: Session) -> dict:
    rows = parse_product_import_file(filename, content)
    tables = _get_tenant_tables_for_user(current_user)
    products = tables["producto"]
    suppliers = tables["proveedor"]

    import_errors = []
    skus = [row["sku"] for row in rows]
    existing_skus = set()
    if skus:
        existing_skus = {
            row["sku"]
            for row in db.execute(select(products.c.sku).where(products.c.sku.in_(skus))).mappings()
        }
    for index, row in enumerate(rows, start=2):
        if row["sku"] in existing_skus:
            import_errors.append({"row": index, "column": "sku", "code": "existing_sku", "message": "SKU already exists"})

        proveedor_id = row.get("proveedor_id")
        if proveedor_id:
            supplier = db.execute(
                select(suppliers.c.id, suppliers.c.is_active).where(suppliers.c.id == proveedor_id)
            ).mappings().first()
            if supplier is None:
                import_errors.append(
                    {"row": index, "column": "proveedor_id", "code": "supplier_not_found", "message": "Supplier not found"}
                )
            elif not supplier["is_active"]:
                import_errors.append(
                    {"row": index, "column": "proveedor_id", "code": "supplier_inactive", "message": "Supplier is inactive"}
                )

    if import_errors:
        raise ProductImportError("Invalid product import rows", "invalid_rows", import_errors)

    now = _utcnow()
    product_ids = [uuid4() for _row in rows]
    insert_rows = [
        {
            "id": product_id,
            "proveedor_id": row.get("proveedor_id"),
            "sku": row["sku"],
            "nombre": row["nombre"],
            "descripcion": row.get("descripcion"),
            "precio_venta": row["precio_venta"],
            "stock_actual": Decimal("0"),
            "stock_minimo": row["stock_minimo"],
            "unidad_medida": row["unidad_medida"],
            "updated_at": now,
        }
        for product_id, row in zip(product_ids, rows)
    ]
    try:
        if insert_rows:
            db.execute(insert(products), insert_rows)
        db.commit()
    except Exception:
        db.rollback()
        raise

    inserted = [
        dict(row)
        for row in db.execute(select(products).where(products.c.id.in_(product_ids))).mappings()
    ]
    return {"inserted": len(inserted), "products": inserted}


def parse_product_import_file(filename: str, content: bytes) -> list[dict]:
    if not content:
        raise ProductImportError("Import file is empty", "empty_file", [])

    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension == "csv":
        raw_rows = _read_csv_rows(content)
    elif extension == "xlsx":
        raw_rows = _read_xlsx_rows(content)
    else:
        raise ProductImportError("Unsupported import file format", "unsupported_format", [])

    if not raw_rows:
        raise ProductImportError("Import file is empty", "empty_file", [])

    return _normalize_product_import_rows(raw_rows)


def _read_csv_rows(content: bytes) -> list[dict]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ProductImportError("CSV file must be UTF-8 encoded", "invalid_format", [])
    reader = csv.DictReader(StringIO(text))
    if not reader.fieldnames:
        raise ProductImportError("Import file is empty", "empty_file", [])
    return list(reader)


def _read_xlsx_rows(content: bytes) -> list[dict]:
    try:
        with zipfile.ZipFile(BytesIO(content)) as workbook:
            shared_strings = _read_xlsx_shared_strings(workbook)
            sheet_xml = workbook.read("xl/worksheets/sheet1.xml")
    except (KeyError, zipfile.BadZipFile):
        raise ProductImportError("Invalid XLSX file", "invalid_format", [])

    try:
        root = ElementTree.fromstring(sheet_xml)
    except ElementTree.ParseError:
        raise ProductImportError("Invalid XLSX file", "invalid_format", [])
    namespace = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    matrix = []
    for row in root.findall(".//a:sheetData/a:row", namespace):
        values = {}
        for cell in row.findall("a:c", namespace):
            reference = cell.attrib.get("r", "")
            column = _xlsx_column_index(reference)
            values[column] = _read_xlsx_cell_value(cell, shared_strings, namespace)
        if values:
            matrix.append([values.get(index, "") for index in range(max(values) + 1)])
    if not matrix:
        return []
    headers = [str(value).strip() for value in matrix[0]]
    rows = []
    for values in matrix[1:]:
        if not any(str(value).strip() for value in values):
            continue
        rows.append({header: values[index] if index < len(values) else "" for index, header in enumerate(headers)})
    return rows


def _read_xlsx_shared_strings(workbook: zipfile.ZipFile) -> list[str]:
    try:
        shared_xml = workbook.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    namespace = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    try:
        root = ElementTree.fromstring(shared_xml)
    except ElementTree.ParseError:
        return []
    strings = []
    for item in root.findall("a:si", namespace):
        text_parts = [node.text or "" for node in item.findall(".//a:t", namespace)]
        strings.append("".join(text_parts))
    return strings


def _read_xlsx_cell_value(cell, shared_strings: list[str], namespace: dict[str, str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        text = cell.find(".//a:t", namespace)
        return text.text if text is not None and text.text is not None else ""
    value = cell.find("a:v", namespace)
    if value is None or value.text is None:
        return ""
    if cell_type == "s":
        try:
            index = int(value.text)
        except ValueError:
            return ""
        return shared_strings[index] if index < len(shared_strings) else ""
    return value.text


def _xlsx_column_index(reference: str) -> int:
    match = re.match(r"([A-Z]+)", reference)
    if not match:
        return 0
    index = 0
    for char in match.group(1):
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index - 1


def _normalize_product_import_rows(raw_rows: list[dict]) -> list[dict]:
    normalized_headers = {_normalize_header(header): header for header in raw_rows[0].keys() if header is not None}
    columns = set(normalized_headers)
    missing = sorted(PRODUCT_IMPORT_REQUIRED_COLUMNS - columns)
    unexpected = sorted(columns - PRODUCT_IMPORT_ALLOWED_COLUMNS)
    if missing or unexpected:
        errors = [
            {"column": column, "code": "missing_column", "message": "Required column is missing"}
            for column in missing
        ]
        errors.extend(
            {"column": column, "code": "unexpected_column", "message": "Column is not allowed"}
            for column in unexpected
        )
        raise ProductImportError("Invalid product import columns", "invalid_columns", errors)

    rows = []
    errors = []
    seen_skus = {}
    for index, raw_row in enumerate(raw_rows, start=2):
        row = {_normalize_header(key): value for key, value in raw_row.items() if key is not None}
        if not any(_clean_text(value) for value in row.values()):
            continue

        sku = _clean_text(row.get("sku"))
        nombre = _clean_text(row.get("nombre"))
        if not sku:
            errors.append({"row": index, "column": "sku", "code": "required", "message": "SKU is required"})
        if not nombre:
            errors.append({"row": index, "column": "nombre", "code": "required", "message": "Nombre is required"})
        if sku:
            if sku in seen_skus:
                errors.append({"row": index, "column": "sku", "code": "duplicate_sku", "message": "SKU is duplicated in file"})
            else:
                seen_skus[sku] = index

        normalized = {
            "sku": sku,
            "nombre": nombre,
            "descripcion": _clean_optional_text(row.get("descripcion")),
            "precio_venta": _parse_nonnegative_decimal(row.get("precio_venta"), "precio_venta", index, errors),
            "stock_minimo": _parse_nonnegative_decimal(row.get("stock_minimo"), "stock_minimo", index, errors),
            "unidad_medida": _clean_text(row.get("unidad_medida")) or "unidad",
            "proveedor_id": _parse_optional_uuid(row.get("proveedor_id"), "proveedor_id", index, errors),
        }
        rows.append(normalized)

    if errors:
        raise ProductImportError("Invalid product import rows", "invalid_rows", errors)
    if not rows:
        raise ProductImportError("Import file is empty", "empty_file", [])
    return rows


def _normalize_header(value) -> str:
    return str(value or "").strip().lower()


def _clean_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _clean_optional_text(value) -> str | None:
    cleaned = _clean_text(value)
    return cleaned or None


def _parse_nonnegative_decimal(value, column: str, row: int, errors: list[dict]) -> Decimal:
    cleaned = _clean_text(value)
    if not cleaned:
        return Decimal("0")
    try:
        parsed = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        errors.append({"row": row, "column": column, "code": "invalid_decimal", "message": "Value must be numeric"})
        return Decimal("0")
    if parsed < Decimal("0"):
        errors.append({"row": row, "column": column, "code": "negative_decimal", "message": "Value must be non-negative"})
        return Decimal("0")
    return parsed


def _parse_optional_uuid(value, column: str, row: int, errors: list[dict]) -> UUID | None:
    cleaned = _clean_text(value)
    if not cleaned:
        return None
    try:
        return UUID(cleaned)
    except ValueError:
        errors.append({"row": row, "column": column, "code": "invalid_uuid", "message": "Value must be a valid UUID"})
        return None


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


def get_monthly_behavior(
    current_user: User,
    db: Session,
    *,
    period: AnalyticsPeriod,
    product_id: UUID | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    analytics_range = _resolve_analytics_range(period, start_date, end_date)
    rows = _fetch_analytics_rows(current_user, db, analytics_range, product_id)
    points = _aggregate_movement_rows(rows, window="month", include_previous=True)
    return {
        "period": period,
        "product_id": product_id,
        "start_date": analytics_range["start"].date(),
        "end_date": analytics_range["end"].date(),
        "points": points,
    }


def get_inventory_trend(
    current_user: User,
    db: Session,
    *,
    period: AnalyticsPeriod,
    window: AnalyticsWindow,
    product_id: UUID | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    analytics_range = _resolve_analytics_range(period, start_date, end_date)
    rows = _fetch_analytics_rows(current_user, db, analytics_range, product_id)
    points = _aggregate_movement_rows(rows, window=window, include_previous=False)
    return {
        "period": period,
        "window": window,
        "product_id": product_id,
        "start_date": analytics_range["start"].date(),
        "end_date": analytics_range["end"].date(),
        "points": points,
    }


def get_product_analytics(
    current_user: User,
    db: Session,
    *,
    period: AnalyticsPeriod,
    sort_by: ProductAnalyticsSort,
    limit: int,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    analytics_range = _resolve_analytics_range(period, start_date, end_date)
    rows = _fetch_analytics_rows(current_user, db, analytics_range, product_id=None)
    products = _rank_product_rows(rows, sort_by=sort_by, limit=limit)
    return {
        "period": period,
        "sort_by": sort_by,
        "start_date": analytics_range["start"].date(),
        "end_date": analytics_range["end"].date(),
        "products": products,
    }


def get_inventory_metrics(
    current_user: User,
    db: Session,
    *,
    period: AnalyticsPeriod,
    product_id: UUID | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    analytics_range = _resolve_analytics_range(period, start_date, end_date)
    tables = _get_tenant_tables_for_user(current_user)
    products = tables["producto"]
    movements = tables["movimiento_inventario"]

    product_query = select(
        products.c.stock_actual,
        products.c.stock_minimo,
        products.c.is_active,
    ).where(products.c.is_active.is_(True))
    movement_query = (
        select(movements.c.tipo_movimiento, movements.c.cantidad)
        .where(movements.c.fecha >= analytics_range["start"])
        .where(movements.c.fecha <= analytics_range["end"])
    )
    if product_id is not None:
        product_query = product_query.where(products.c.id == product_id)
        movement_query = movement_query.where(movements.c.producto_id == product_id)

    summary = summarize_inventory_metrics(
        [dict(row) for row in db.execute(product_query).mappings()],
        [dict(row) for row in db.execute(movement_query).mappings()],
    )
    return {
        "period": period,
        "product_id": product_id,
        "start_date": analytics_range["start"].date(),
        "end_date": analytics_range["end"].date(),
        **summary,
    }


def list_inventory_history(
    current_user: User,
    db: Session,
    *,
    limit: int,
    product_id: UUID | None = None,
    movement_type: MovementType | None = None,
) -> list[dict]:
    tables = _get_tenant_tables_for_user(current_user)
    products = tables["producto"]
    movements = tables["movimiento_inventario"]
    query = (
        select(
            movements.c.id,
            movements.c.producto_id,
            products.c.sku,
            products.c.nombre,
            movements.c.tipo_movimiento,
            movements.c.fecha,
            movements.c.cantidad,
            movements.c.stock_resultante,
            movements.c.motivo,
        )
        .select_from(movements.join(products, movements.c.producto_id == products.c.id))
        .order_by(movements.c.fecha.desc())
        .limit(limit)
    )
    if product_id is not None:
        query = query.where(movements.c.producto_id == product_id)
    if movement_type is not None:
        query = query.where(movements.c.tipo_movimiento == movement_type)
    return [format_inventory_history_row(dict(row)) for row in db.execute(query).mappings()]


def summarize_inventory_metrics(products: list[dict], movements: list[dict]) -> dict:
    entradas = Decimal("0")
    salidas = Decimal("0")
    for movement in movements:
        quantity = _to_decimal(movement["cantidad"])
        if _movement_direction(movement["tipo_movimiento"]) == "in":
            entradas += quantity
        else:
            salidas += quantity

    stock_bajo = 0
    sin_stock = 0
    for product in products:
        if not product.get("is_active", True):
            continue
        stock_actual = _to_decimal(product["stock_actual"])
        stock_minimo = _to_decimal(product["stock_minimo"])
        if stock_actual <= Decimal("0"):
            sin_stock += 1
        elif stock_actual <= stock_minimo:
            stock_bajo += 1

    return {
        "entradas": entradas,
        "salidas": salidas,
        "stock_bajo": stock_bajo,
        "sin_stock": sin_stock,
    }


def format_inventory_history_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "producto_id": row["producto_id"],
        "sku": row["sku"],
        "nombre": row["nombre"],
        "tipo_movimiento": row["tipo_movimiento"],
        "direction": _movement_direction(row["tipo_movimiento"]),
        "fecha": row["fecha"],
        "cantidad": _to_decimal(row["cantidad"]),
        "stock_resultante": _to_decimal(row["stock_resultante"]),
        "motivo": row.get("motivo"),
    }


def _get_tenant_tables_for_user(current_user: User) -> dict:
    schema_name = get_user_schema_name(current_user)
    return get_tenant_tables(schema_name)


def _fetch_analytics_rows(
    current_user: User,
    db: Session,
    analytics_range: dict,
    product_id: UUID | None,
) -> list[dict]:
    tables = _get_tenant_tables_for_user(current_user)
    products = tables["producto"]
    movements = tables["movimiento_inventario"]
    query = (
        select(
            movements.c.producto_id,
            movements.c.tipo_movimiento,
            movements.c.fecha,
            movements.c.cantidad,
            movements.c.stock_resultante,
            products.c.sku,
            products.c.nombre,
            products.c.stock_actual,
            products.c.stock_minimo,
        )
        .select_from(movements.join(products, movements.c.producto_id == products.c.id))
        .where(movements.c.fecha >= analytics_range["start"])
        .where(movements.c.fecha <= analytics_range["end"])
        .order_by(movements.c.fecha.asc())
    )
    if product_id is not None:
        query = query.where(movements.c.producto_id == product_id)
    return [dict(row) for row in db.execute(query).mappings()]


def _resolve_analytics_range(
    period: AnalyticsPeriod,
    start_date: date | None,
    end_date: date | None,
    *,
    now: datetime | None = None,
) -> dict:
    current = now or _utcnow()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    resolved_end = _date_to_datetime(end_date, end_of_day=True) if end_date else current

    if period == "custom":
        if start_date is None or end_date is None:
            raise AppError(status_code=400, message="Custom analytics period requires start_date and end_date")
        resolved_start = _date_to_datetime(start_date)
    elif period == "ytd":
        resolved_start = datetime(resolved_end.year, 1, 1, tzinfo=timezone.utc)
    else:
        resolved_start = resolved_end - timedelta(days=PERIOD_DAYS[period])

    if resolved_start > resolved_end:
        raise AppError(status_code=400, message="start_date must be before end_date")
    return {"start": resolved_start, "end": resolved_end}


def _aggregate_movement_rows(
    rows: list[dict],
    *,
    window: AnalyticsWindow,
    include_previous: bool,
) -> list[dict]:
    buckets = {}
    for row in rows:
        bucket_start = _bucket_start(row["fecha"], window)
        bucket = buckets.setdefault(bucket_start, _empty_bucket(bucket_start, window))
        quantity = _to_decimal(row["cantidad"])
        if _movement_direction(row["tipo_movimiento"]) == "in":
            bucket["inbound_quantity"] += quantity
        else:
            bucket["outbound_quantity"] += quantity
        bucket["net_quantity"] = bucket["inbound_quantity"] - bucket["outbound_quantity"]
        bucket["movement_count"] += 1
        bucket["ending_stock"] = _to_decimal(row["stock_resultante"])

    points = [buckets[key] for key in sorted(buckets)]
    if include_previous:
        previous = None
        for point in points:
            current_net = point["net_quantity"]
            point["previous_net_quantity"] = previous
            point["net_change_quantity"] = None if previous is None else current_net - previous
            if previous in (None, Decimal("0")):
                point["net_change_percent"] = None
            else:
                point["net_change_percent"] = ((current_net - previous) / abs(previous) * Decimal("100")).quantize(
                    Decimal("0.01")
                )
            previous = current_net
    return points


def _rank_product_rows(
    rows: list[dict],
    *,
    sort_by: ProductAnalyticsSort,
    limit: int,
) -> list[dict]:
    products = {}
    for row in rows:
        product_id = row["producto_id"]
        product = products.setdefault(
            product_id,
            {
                "product_id": product_id,
                "sku": row["sku"],
                "nombre": row["nombre"],
                "inbound_quantity": Decimal("0"),
                "outbound_quantity": Decimal("0"),
                "net_quantity": Decimal("0"),
                "movement_count": 0,
                "ending_stock": _to_decimal(row["stock_actual"]),
                "stock_minimo": _to_decimal(row["stock_minimo"]),
                "stock_risk_score": Decimal("0"),
            },
        )
        quantity = _to_decimal(row["cantidad"])
        if _movement_direction(row["tipo_movimiento"]) == "in":
            product["inbound_quantity"] += quantity
        else:
            product["outbound_quantity"] += quantity
        product["net_quantity"] = product["inbound_quantity"] - product["outbound_quantity"]
        product["movement_count"] += 1
        product["ending_stock"] = _to_decimal(row["stock_resultante"])
        product["stock_risk_score"] = _stock_risk_score(
            product["ending_stock"],
            product["stock_minimo"],
            product["outbound_quantity"],
        )

    return sorted(products.values(), key=lambda product: _product_sort_key(product, sort_by), reverse=True)[:limit]


def _product_sort_key(product: dict, sort_by: ProductAnalyticsSort):
    if sort_by == "outbound":
        return (product["outbound_quantity"], product["movement_count"])
    if sort_by == "inbound":
        return (product["inbound_quantity"], product["movement_count"])
    if sort_by == "net":
        return (abs(product["net_quantity"]), product["movement_count"])
    if sort_by == "movement_count":
        return (product["movement_count"], product["outbound_quantity"])
    return (product["stock_risk_score"], product["outbound_quantity"])


def _stock_risk_score(ending_stock: Decimal, stock_minimo: Decimal, outbound_quantity: Decimal) -> Decimal:
    if stock_minimo <= Decimal("0"):
        return Decimal("0")
    shortage_ratio = max(Decimal("0"), (stock_minimo - ending_stock) / stock_minimo)
    demand_weight = outbound_quantity / (outbound_quantity + stock_minimo) if outbound_quantity > 0 else Decimal("0")
    return ((shortage_ratio * Decimal("70")) + (demand_weight * Decimal("30"))).quantize(Decimal("0.01"))


def _empty_bucket(bucket_start: date, window: AnalyticsWindow) -> dict:
    return {
        "period_start": bucket_start,
        "period_label": _bucket_label(bucket_start, window),
        "inbound_quantity": Decimal("0"),
        "outbound_quantity": Decimal("0"),
        "net_quantity": Decimal("0"),
        "movement_count": 0,
        "ending_stock": None,
    }


def _bucket_start(value: datetime, window: AnalyticsWindow) -> date:
    value_date = value.date()
    if window == "day":
        return value_date
    if window == "week":
        return value_date - timedelta(days=value_date.weekday())
    return date(value_date.year, value_date.month, 1)


def _bucket_label(bucket_start: date, window: AnalyticsWindow) -> str:
    if window == "month":
        return bucket_start.strftime("%Y-%m")
    if window == "week":
        return f"{bucket_start.isoformat()} week"
    return bucket_start.isoformat()


def _date_to_datetime(value: date, *, end_of_day: bool = False) -> datetime:
    if end_of_day:
        return datetime.combine(value, time.max, tzinfo=timezone.utc)
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


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

def update_product_status(current_user: User, db: Session, product_id, is_active: bool) -> dict:
    tables = _get_tenant_tables_for_user(current_user)
    products = tables["producto"]

    product = db.execute(
        select(products).where(products.c.id == product_id)
    ).mappings().first()

    if product is None:
        raise AppError(status_code=404, message="Product not found")

    if product["is_active"] == is_active:
        raise AppError(status_code=400, message="Product already has this status")

    now = _utcnow()

    try:
        db.execute(
            update(products)
            .where(products.c.id == product_id)
            .values(is_active=is_active, updated_at=now)
        )
        db.commit()
    except Exception as e:
        db.rollback()
        raise AppError(500, f"Failed to update product status: {str(e)}")

    updated = db.execute(
        select(products).where(products.c.id == product_id)
    ).mappings().one()

    return dict(updated)