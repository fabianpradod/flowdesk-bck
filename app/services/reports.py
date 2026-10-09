from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from app.models.users import User
from app.schemas.inventory import AnalyticsPeriod, MovementType
from app.schemas.reports import ReportDataset, ReportFormat, ReportSheet, ReportType, ReportWorkbook, TaxReportRegime
from app.services.inventory import (
    _get_tenant_tables_for_user,
    _resolve_analytics_range,
    _to_decimal,
    _utcnow,
    format_inventory_history_row,
)
from app.services.analytics import FINAL_SALE_STATES
from app.services import fiscal_documents, tax_period
from app.services.taxation import resolve_current_profile
from app.taxation.fiscal_adapter import document_tax_components
from app.utils.csv_report import render_csv
from app.utils.exceptions import AppError
from app.utils.logger import logger
from app.utils.pdf_report import render_pdf
from app.utils.xlsx_report import render_xlsx

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

SMALL_PURCHASE_COLUMNS = [
    "No.", "Fecha", "Tipo Documento", "Número Documento", "NIT Proveedor",
    "Nombre Proveedor", "Total Compra",
]
SMALL_SALE_COLUMNS = [
    "No.", "Fecha", "Número Factura", "NIT Comprador", "Nombre Comprador", "Total Venta",
]
GENERAL_COLUMNS = [
    "No.", "Fecha", "Tipo Documento", "Serie / Autorización", "Número Documento",
    "NIT", "Nombre", "Valor Neto / Base", "IVA", "Total Documento",
]


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

def build_tax_report(
    current_user: User,
    db: Session,
    *,
    regime: TaxReportRegime,
    period: AnalyticsPeriod = "30d",
    start_date: date | None = None,
    end_date: date | None = None,
) -> ReportWorkbook:
    """Build the internal tax-control workbook from tenant-scoped data.

    Sales remain historical ``Venta`` snapshots. Input purchases come only
    from persisted ``FiscalDocument`` records and their tax components; they
    are never inferred from inventory movements.
    """
    analytics_range = _resolve_analytics_range(period, start_date, end_date)
    tables = _get_tenant_tables_for_user(current_user)
    sales = tables["venta"]
    clients = tables["cliente"]
    query = (
        select(
            sales.c.fecha,
            sales.c.subtotal,
            sales.c.descuento,
            sales.c.impuesto,
            sales.c.tasa_impuesto,
            sales.c.total,
            sales.c.es_exenta,
            clients.c.nombre.label("cliente_nombre"),
        )
        .select_from(sales.outerjoin(clients, sales.c.cliente_id == clients.c.id))
        .where(
            sales.c.fecha >= analytics_range["start"],
            sales.c.fecha <= analytics_range["end"],
            func.lower(sales.c.estado).in_(FINAL_SALE_STATES),
        )
        .order_by(sales.c.fecha.asc(), sales.c.id.asc())
    )
    sales_rows = [dict(row) for row in db.execute(query).mappings()]
    debit = _get_fiscal_debit_for_report(current_user, db, period, start_date, end_date)
    input_documents = _get_input_documents_for_report(
        current_user, db, analytics_range["start"].date(), analytics_range["end"].date()
    )
    period_result = None
    if input_documents:
        try:
            period_result = tax_period.calculate_period(
                current_user, db,
                start_date=analytics_range["start"].date(),
                end_date=analytics_range["end"].date(),
                include_details=True,
            )
        except AppError as exc:
            if getattr(exc, "status_code", None) != 404:
                raise

    sale_sheet = _build_tax_sales_sheet(sales_rows, regime)
    profile = (lambda issue_date: _resolve_report_profile(current_user, db, issue_date)) if input_documents else None
    purchase_sheet = ReportSheet(
        name="Compras",
        columns=SMALL_PURCHASE_COLUMNS if regime == "SMALL_TAXPAYER" else GENERAL_COLUMNS,
        rows=_build_tax_purchase_rows(input_documents, regime, profile),
    )
    summary = _build_tax_summary(regime, sales_rows, debit, period_result=period_result, input_documents=input_documents)
    return ReportWorkbook(
        title="Reporte Tributario",
        sheets=[purchase_sheet, sale_sheet, summary],
        metadata=_build_metadata(
            current_user,
            filters=[f"Régimen: {regime}"],
            analytics_range=analytics_range,
        ),
    )

def generate_tax_report(
    report: ReportWorkbook,
    current_user: User,
    db: Session,
) -> tuple[bytes, str]:
    payload = render_xlsx(report)
    _record_generation(current_user, db, report, report_type="tributario", report_format="xlsx")
    return payload, build_filename("tributario", "xlsx")

def _build_tax_sales_sheet(rows: list[dict], regime: TaxReportRegime) -> ReportSheet:
    if regime == "SMALL_TAXPAYER":
        values = [
            [index, _date_value(row["fecha"]), None, None,
             row["cliente_nombre"] or "Consumidor Final", _money(row["total"])]
            for index, row in enumerate(rows, start=1)
        ]
        return ReportSheet("Ventas", SMALL_SALE_COLUMNS, values)

    values = [
        [index, _date_value(row["fecha"]), "Venta", None, None, None,
         row["cliente_nombre"] or "Consumidor Final",
         _money(_to_decimal(row["subtotal"]) - _to_decimal(row["descuento"])),
         _money(row["impuesto"]), _money(row["total"])]
        for index, row in enumerate(rows, start=1)
    ]
    return ReportSheet("Ventas", GENERAL_COLUMNS, values)

def _build_tax_summary(regime: TaxReportRegime, rows: list[dict], debit: dict, *, period_result: dict | None = None, input_documents: list[dict] | None = None) -> ReportSheet:
    income = sum((_to_decimal(row["total"]) for row in rows), Decimal("0.00"))
    rates = {_to_decimal(row["tasa_impuesto"]) for row in rows}
    # A single historical rate is numeric. Multiple rates do not have one
    # truthful scalar representation, so the Excel cell remains empty.
    rate_value = next(iter(rates)) if len(rates) == 1 else None
    if regime == "SMALL_TAXPAYER":
        values = [
            ["Ingresos por ventas/servicios", _money(income)],
            ["Tipo impositivo", rate_value],
            ["Impuesto determinado", _money(debit["fiscal_debit"])],
            ["Retenciones", None],
            ["Impuesto estimado", None],
        ]
    else:
        values = [
            ["Ventas netas", _money(sum((_to_decimal(row["subtotal"]) - _to_decimal(row["descuento"]) for row in rows), Decimal("0.00")))],
            ["Débito fiscal", _money(debit["fiscal_debit"])],
            ["Compras con derecho a crédito", None],
            ["Crédito fiscal", None],
            ["Diferencia débito - crédito", None],
        ]
    if regime == "SMALL_TAXPAYER" and period_result and input_documents:
        values[3][1] = _money_or_none(period_result.get("withholding_tax"))
    if regime != "SMALL_TAXPAYER":
        tax_debit = period_result["tax_debit"] if period_result else _money(debit["fiscal_debit"])
        tax_credit = period_result["tax_credit"] if period_result and input_documents else None
        credit_base = _eligible_purchase_base(period_result) if period_result and input_documents else None
        values[1][1] = _money(tax_debit)
        values[2][1] = _money(credit_base) if credit_base is not None else None
        values[3][1] = _money(tax_credit) if tax_credit is not None else None
        values[4][1] = _money(period_result["net_tax"]) if period_result else None
    return ReportSheet("Resumen", ["Concepto", "Valor"], values)

def _get_fiscal_debit_for_report(current_user, db, period, start_date, end_date) -> dict:
    from app.services.analytics import get_fiscal_debit

    return get_fiscal_debit(
        current_user, db, period=period, start_date=start_date, end_date=end_date
    )

def _get_input_documents_for_report(current_user, db, start_date: date, end_date: date) -> list[dict]:
    documents = _get_tenant_tables_for_user(current_user)["fiscal_document"]
    query = select(documents).where(
        documents.c.direction == "INPUT",
        documents.c.issue_date >= start_date,
        documents.c.issue_date <= end_date,
        documents.c.status.not_in(("CANCELLED", "VOIDED")),
    ).order_by(documents.c.issue_date.asc(), documents.c.created_at.asc())
    return [fiscal_documents.get_document(row["id"], current_user, db) for row in db.execute(query).mappings()]

def _resolve_report_profile(current_user, db, on_date):
    try:
        return resolve_current_profile(current_user, db, on_date)
    except AppError as exc:
        if getattr(exc, "status_code", None) == 404:
            return None
        raise

def _build_tax_purchase_rows(documents: list[dict], regime: TaxReportRegime, profile) -> list[list]:
    rows = []
    for index, document in enumerate(documents, start=1):
        issue_date = _date_value(document["issue_date"])
        number = document.get("document_number")
        issuer_id = document.get("issuer_tax_identifier")
        issuer_name = document.get("issuer_name")
        if regime == "SMALL_TAXPAYER":
            rows.append([index, issue_date, document.get("document_type"), number, issuer_id, issuer_name, _money_or_none(document.get("total"))])
        else:
            rows.append([
                index, issue_date, document.get("document_type"),
                _join_document_identity(document.get("series"), document.get("authorization_number")),
                number, issuer_id, issuer_name, _money_or_none(document.get("taxable_base")),
                _report_tax_amount(document, profile), _money_or_none(document.get("total")),
            ])
    return rows

def _join_document_identity(series, authorization):
    values = [value for value in (series, authorization) if value]
    return " / ".join(values) if values else None

def _report_tax_amount(document, profile):
    if callable(profile):
        profile = profile(document.get("issue_date"))
    if profile is None:
        return None
    configured_codes = {tax.tax_code for tax in profile.taxes}
    components = [component for component in document_tax_components(document)
                  if component.get("tax_code") in configured_codes and not component.get("is_withholding", False)]
    codes = {component.get("tax_code") for component in components}
    if len(codes) != 1:
        return None
    return _money(sum((_to_decimal(component.get("amount")) for component in components), Decimal("0")))

def _eligible_purchase_base(period_result):
    return sum((
        _to_decimal(detail.get("taxable_base"))
        for detail in period_result.get("details", [])
        if detail.get("eligible_for_input_credit")
    ), Decimal("0"))

def _date_value(value: datetime | date) -> date:
    return value.date() if isinstance(value, datetime) else value

def _money(value) -> Decimal:
    return _to_decimal(value).quantize(Decimal("0.01"))

def _money_or_none(value):
    return None if value is None else _money(value)

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
