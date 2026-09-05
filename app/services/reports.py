from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.models.users import User
from app.schemas.inventory import AnalyticsPeriod, MovementType
from app.schemas.reports import ReportDataset, ReportFormat, ReportType
from app.services.inventory import (
    _get_tenant_tables_for_user,
    _resolve_analytics_range,
    _to_decimal,
    _utcnow,
    format_inventory_history_row,
)
from app.utils.csv_report import render_csv
from app.utils.exceptions import AppError
from app.utils.logger import logger
from app.utils.pdf_report import render_pdf

INVENTORY_COLUMNS = [
    "SKU",
    "Nombre",
    "Proveedor",
    "Stock Actual",
    "Stock Mínimo",
    "Precio",
    "Unidad",
    "Estado",
]
MOVEMENT_COLUMNS = [
    "Fecha",
    "SKU",
    "Producto",
    "Tipo",
    "Dirección",
    "Cantidad",
    "Stock Resultante",
    "Motivo",
]
ALERT_COLUMNS = [
    "Fecha",
    "SKU",
    "Producto",
    "Tipo",
    "Mensaje",
    "Estado",
    "Resuelta En",
]

MOVEMENT_TYPE_LABELS = {
    "entrada_compra": "Entrada por compra",
    "entrada_manual": "Entrada manual",
    "ajuste_positivo": "Ajuste positivo",
    "devolucion_cliente": "Devolución de cliente",
    "salida_venta": "Salida por venta",
    "salida_manual": "Salida manual",
    "ajuste_negativo": "Ajuste negativo",
    "devolucion_proveedor": "Devolución a proveedor",
}
DIRECTION_LABELS = {"in": "Entrada", "out": "Salida"}
EMPTY_CELL = "—"
GENERATED_STATUS = "generado"
RENDERERS = {"csv": render_csv, "pdf": render_pdf}


def build_inventory_dataset(
    current_user: User,
    db: Session,
    *,
    product_id: UUID | None = None,
    is_active: bool | None = None,
    only_low_stock: bool = False,
) -> ReportDataset:
    tables = _get_tenant_tables_for_user(current_user)
    products = tables["producto"]
    suppliers = tables["proveedor"]

    query = (
        select(
            products.c.sku,
            products.c.nombre,
            suppliers.c.nombre.label("proveedor"),
            products.c.stock_actual,
            products.c.stock_minimo,
            products.c.precio_venta,
            products.c.unidad_medida,
            products.c.is_active,
        )
        .select_from(products.outerjoin(suppliers, products.c.proveedor_id == suppliers.c.id))
        .order_by(products.c.nombre.asc())
    )
    if product_id is not None:
        query = query.where(products.c.id == product_id)
    if is_active is not None:
        query = query.where(products.c.is_active == is_active)
    if only_low_stock:
        query = query.where(products.c.stock_actual <= products.c.stock_minimo)

    rows = [
        [
            _text(row["sku"]),
            _text(row["nombre"]),
            _text(row["proveedor"]),
            _number(row["stock_actual"]),
            _number(row["stock_minimo"]),
            _number(row["precio_venta"]),
            _text(row["unidad_medida"]),
            "Activo" if row["is_active"] else "Inactivo",
        ]
        for row in db.execute(query).mappings()
    ]

    filters = [
        f"Producto: {'uno' if product_id else 'todos'}",
        f"Estado: {_status_filter_label(is_active)}",
        f"Solo stock bajo: {'sí' if only_low_stock else 'no'}",
    ]
    return ReportDataset(
        title="Reporte de Inventario",
        columns=INVENTORY_COLUMNS,
        rows=rows,
        metadata=_build_metadata(current_user, filters=filters),
    )


def build_movements_dataset(
    current_user: User,
    db: Session,
    *,
    period: AnalyticsPeriod = "30d",
    start_date: date | None = None,
    end_date: date | None = None,
    product_id: UUID | None = None,
    movement_type: MovementType | None = None,
) -> ReportDataset:
    analytics_range = _resolve_analytics_range(period, start_date, end_date)
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
        .where(movements.c.fecha >= analytics_range["start"])
        .where(movements.c.fecha <= analytics_range["end"])
        .order_by(movements.c.fecha.desc())
    )
    if product_id is not None:
        query = query.where(movements.c.producto_id == product_id)
    if movement_type is not None:
        query = query.where(movements.c.tipo_movimiento == movement_type)

    rows = []
    for row in db.execute(query).mappings():
        movement = format_inventory_history_row(dict(row))
        rows.append(
            [
                _timestamp(movement["fecha"]),
                _text(movement["sku"]),
                _text(movement["nombre"]),
                MOVEMENT_TYPE_LABELS.get(movement["tipo_movimiento"], _label(movement["tipo_movimiento"])),
                DIRECTION_LABELS[movement["direction"]],
                _number(movement["cantidad"]),
                _number(movement["stock_resultante"]),
                _text(movement["motivo"]),
            ]
        )

    filters = [
        f"Producto: {'uno' if product_id else 'todos'}",
        f"Tipo: {_movement_type_filter_label(movement_type)}",
    ]
    return ReportDataset(
        title="Reporte de Movimientos",
        columns=MOVEMENT_COLUMNS,
        rows=rows,
        metadata=_build_metadata(current_user, filters=filters, analytics_range=analytics_range),
    )


def build_alerts_dataset(
    current_user: User,
    db: Session,
    *,
    period: AnalyticsPeriod = "30d",
    start_date: date | None = None,
    end_date: date | None = None,
    open_only: bool = True,
) -> ReportDataset:
    analytics_range = _resolve_analytics_range(period, start_date, end_date)
    tables = _get_tenant_tables_for_user(current_user)
    products = tables["producto"]
    alerts = tables["alerta"]

    query = (
        select(
            alerts.c.fecha,
            products.c.sku,
            products.c.nombre,
            alerts.c.tipo,
            alerts.c.mensaje,
            alerts.c.estado,
            alerts.c.resuelta_en,
        )
        .select_from(alerts.join(products, alerts.c.producto_id == products.c.id))
        .where(alerts.c.fecha >= analytics_range["start"])
        .where(alerts.c.fecha <= analytics_range["end"])
        .order_by(alerts.c.fecha.desc())
    )
    if open_only:
        query = query.where(alerts.c.estado == "pendiente")

    rows = [
        [
            _timestamp(row["fecha"]),
            _text(row["sku"]),
            _text(row["nombre"]),
            _label(row["tipo"]),
            _text(row["mensaje"]),
            _label(row["estado"]),
            _timestamp(row["resuelta_en"]),
        ]
        for row in db.execute(query).mappings()
    ]

    filters = [f"Solo abiertas: {'sí' if open_only else 'no'}"]
    return ReportDataset(
        title="Reporte de Alertas",
        columns=ALERT_COLUMNS,
        rows=rows,
        metadata=_build_metadata(current_user, filters=filters, analytics_range=analytics_range),
    )


def _build_metadata(
    current_user: User,
    *,
    filters: list[str],
    analytics_range: dict | None = None,
) -> dict:
    company = getattr(current_user, "company", None)
    periodo_inicio = analytics_range["start"].date() if analytics_range else None
    periodo_fin = analytics_range["end"].date() if analytics_range else None
    described = list(filters)
    if analytics_range:
        described.insert(0, f"Periodo: {periodo_inicio} a {periodo_fin}")
    return {
        "empresa": getattr(company, "name", None) or EMPTY_CELL,
        "generado_por": getattr(current_user, "username", None)
        or getattr(current_user, "email", None)
        or EMPTY_CELL,
        "fecha_generacion": _utcnow(),
        "filtros": " · ".join(described),
        "periodo_inicio": periodo_inicio,
        "periodo_fin": periodo_fin,
    }


def _movement_type_filter_label(movement_type: MovementType | None) -> str:
    if movement_type is None:
        return "todos"
    return MOVEMENT_TYPE_LABELS.get(movement_type, _label(movement_type))


def _status_filter_label(is_active: bool | None) -> str:
    if is_active is None:
        return "todos"
    return "activos" if is_active else "inactivos"


def _text(value) -> str:
    if value is None or value == "":
        return EMPTY_CELL
    return str(value)


def _label(value) -> str:
    if not value:
        return EMPTY_CELL
    return str(value).replace("_", " ").capitalize()


def _number(value) -> str:
    if value is None:
        return EMPTY_CELL
    return f"{_to_decimal(value):.2f}"


def _timestamp(value: datetime | None) -> str:
    if value is None:
        return EMPTY_CELL
    return value.strftime("%Y-%m-%d %H:%M")


def generate_report(
    dataset: ReportDataset,
    current_user: User,
    db: Session,
    *,
    report_type: ReportType,
    report_format: ReportFormat,
) -> tuple[bytes, str]:
    """Renders a dataset and records the generation in the tenant's reporte table."""
    renderer = RENDERERS.get(report_format)
    if renderer is None:
        raise AppError(status_code=400, message="Unsupported report format")

    payload = renderer(dataset)
    _record_generation(current_user, db, dataset, report_type=report_type, report_format=report_format)
    return payload, build_filename(report_type, report_format)


def list_report_history(current_user: User, db: Session, *, limit: int = 20) -> list[dict]:
    tables = _get_tenant_tables_for_user(current_user)
    reports = tables["reporte"]
    rows = db.execute(
        select(reports).order_by(reports.c.fecha_generacion.desc()).limit(limit)
    ).mappings()
    return [dict(row) for row in rows]


def build_filename(report_type: ReportType, report_format: ReportFormat) -> str:
    return f"reporte_{report_type}_{_utcnow().date().isoformat()}.{report_format}"


def _record_generation(
    current_user: User,
    db: Session,
    dataset: ReportDataset,
    *,
    report_type: ReportType,
    report_format: ReportFormat,
) -> None:
    tables = _get_tenant_tables_for_user(current_user)
    reports = tables["reporte"]
    try:
        db.execute(
            insert(reports).values(
                id=uuid4(),
                tipo=report_type,
                periodo_inicio=dataset.metadata.get("periodo_inicio"),
                periodo_fin=dataset.metadata.get("periodo_fin"),
                formato=report_format,
                estado=GENERATED_STATUS,
                generado_por_usuario_id=getattr(current_user, "id", None),
                fecha_generacion=_utcnow(),
                ruta_archivo=None,
            )
        )
        db.commit()
    except Exception as e:
        db.rollback()
        logger.exception("Failed to record report generation: %s", e)
        raise AppError(500, "Failed to record report generation")
