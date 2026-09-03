from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models.users import User
from app.schemas.analytics import SalesCustomerType
from app.schemas.inventory import AnalyticsPeriod, AnalyticsWindow
from app.services.inventory import _resolve_analytics_range, _stock_risk_score
from app.tenancy.runtime import get_tenant_tables, get_user_schema_name
from app.utils.exceptions import AppError

FINAL_SALE_STATES = {"completada", "confirmada", "finalizada", "pagada"}
RISK_LEVELS = ("critical", "high", "medium", "low", "healthy")
MONEY_QUANTUM = Decimal("0.01")

def get_sales_metrics(
    current_user: User,
    db: Session,
    *,
    period: AnalyticsPeriod,
    customer_type: SalesCustomerType = "all",
    client_id: UUID | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    analytics_range = _resolve_analytics_range(period, start_date, end_date)
    rows = _fetch_final_sales(
        current_user,
        db,
        analytics_range=analytics_range,
        customer_type=customer_type,
        client_id=client_id,
    )
    return {
        "period": period,
        "customer_type": customer_type,
        "client_id": client_id,
        "start_date": analytics_range["start"].date(),
        "end_date": analytics_range["end"].date(),
        **summarize_sales(rows),
    }

def get_sales_trend(
    current_user: User,
    db: Session,
    *,
    period: AnalyticsPeriod,
    window: AnalyticsWindow,
    customer_type: SalesCustomerType = "all",
    client_id: UUID | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    analytics_range = _resolve_analytics_range(period, start_date, end_date)
    rows = _fetch_final_sales(
        current_user,
        db,
        analytics_range=analytics_range,
        customer_type=customer_type,
        client_id=client_id,
    )
    return {
        "period": period,
        "window": window,
        "customer_type": customer_type,
        "client_id": client_id,
        "start_date": analytics_range["start"].date(),
        "end_date": analytics_range["end"].date(),
        "points": aggregate_sales_trend(rows, window=window),
    }

def get_inventory_risk_distribution(
    current_user: User,
    db: Session,
    *,
    period: AnalyticsPeriod,
    supplier_id: UUID | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    analytics_range = _resolve_analytics_range(period, start_date, end_date)
    tables = _analytics_tables(current_user)
    products = tables["producto"]
    movements = tables["movimiento_inventario"]

    product_query = select(
        products.c.id,
        products.c.stock_actual,
        products.c.stock_minimo,
    ).where(products.c.is_active.is_(True))
    if supplier_id is not None:
        product_query = product_query.where(products.c.proveedor_id == supplier_id)

    movement_query = select(
        movements.c.producto_id,
        movements.c.cantidad,
    ).where(
        movements.c.tipo_movimiento == "salida_venta",
        movements.c.fecha >= analytics_range["start"],
        movements.c.fecha <= analytics_range["end"],
    )

    product_rows = [dict(row) for row in db.execute(product_query).mappings()]
    product_ids = {row["id"] for row in product_rows}
    outbound_by_product: dict[UUID, Decimal] = {}
    if product_ids:
        movement_query = movement_query.where(movements.c.producto_id.in_(product_ids))
        for row in db.execute(movement_query).mappings():
            product_id = row["producto_id"]
            outbound_by_product[product_id] = outbound_by_product.get(product_id, Decimal("0")) + _decimal(
                row["cantidad"]
            )

    scores = [
        _stock_risk_score(
            _decimal(row["stock_actual"]),
            _decimal(row["stock_minimo"]),
            outbound_by_product.get(row["id"], Decimal("0")),
        )
        for row in product_rows
    ]
    return {
        "period": period,
        "supplier_id": supplier_id,
        "start_date": analytics_range["start"].date(),
        "end_date": analytics_range["end"].date(),
        **build_risk_distribution(scores),
    }

def summarize_sales(rows: list[dict[str, Any]]) -> dict[str, Any]:
    gross_sales = sum((_decimal(row["subtotal"]) for row in rows), Decimal("0"))
    discounts = sum((_decimal(row["descuento"]) for row in rows), Decimal("0"))
    taxes = sum((_decimal(row["impuesto"]) for row in rows), Decimal("0"))
    net_sales = sum((_decimal(row["total"]) for row in rows), Decimal("0"))
    sales_count = len(rows)
    return {
        "sales_count": sales_count,
        "gross_sales": _money(gross_sales),
        "discounts": _money(discounts),
        "taxes": _money(taxes),
        "net_sales": _money(net_sales),
        "average_ticket": _money(net_sales / sales_count) if sales_count else Decimal("0.00"),
        "registered_customer_sales": sum(row.get("cliente_id") is not None for row in rows),
        "final_consumer_sales": sum(row.get("cliente_id") is None for row in rows),
    }

def aggregate_sales_trend(rows: list[dict[str, Any]], *, window: AnalyticsWindow) -> list[dict[str, Any]]:
    buckets: dict[date, list[dict[str, Any]]] = {}
    for row in rows:
        bucket = _bucket_start(row["fecha"], window)
        buckets.setdefault(bucket, []).append(row)

    points = []
    for bucket in sorted(buckets):
        summary = summarize_sales(buckets[bucket])
        points.append(
            {
                "period_start": bucket,
                "period_label": _bucket_label(bucket, window),
                "sales_count": summary["sales_count"],
                "gross_sales": summary["gross_sales"],
                "discounts": summary["discounts"],
                "taxes": summary["taxes"],
                "net_sales": summary["net_sales"],
                "average_ticket": summary["average_ticket"],
            }
        )
    return points

def build_risk_distribution(scores: list[Decimal]) -> dict[str, Any]:
    counts = {level: 0 for level in RISK_LEVELS}
    for score in scores:
        counts[_risk_level(_decimal(score))] += 1
    total = len(scores)
    percentages = {
        level: _money(Decimal(counts[level]) * Decimal("100") / total)
        if total
        else Decimal("0.00")
        for level in RISK_LEVELS
    }
    if total:
        last_nonempty = next(level for level in reversed(RISK_LEVELS) if counts[level])
        percentages[last_nonempty] += Decimal("100.00") - sum(percentages.values(), Decimal("0"))
    return {
        "total_products": total,
        "distribution": [
            {
                "level": level,
                "product_count": counts[level],
                "percentage": percentages[level],
            }
            for level in RISK_LEVELS
        ],
    }

def _fetch_final_sales(
    current_user: User,
    db: Session,
    *,
    analytics_range: dict[str, datetime],
    customer_type: SalesCustomerType,
    client_id: UUID | None,
) -> list[dict[str, Any]]:
    if client_id is not None and customer_type == "final_consumer":
        raise AppError(
            status_code=400,
            message="client_id cannot be combined with final_consumer customer_type",
        )
    sales = _analytics_tables(current_user)["venta"]
    query = select(
        sales.c.fecha,
        sales.c.subtotal,
        sales.c.descuento,
        sales.c.impuesto,
        sales.c.total,
        sales.c.cliente_id,
    ).where(
        sales.c.fecha >= analytics_range["start"],
        sales.c.fecha <= analytics_range["end"],
        func.lower(sales.c.estado).in_(FINAL_SALE_STATES),
    )
    if client_id is not None:
        query = query.where(sales.c.cliente_id == client_id)
    elif customer_type == "registered":
        query = query.where(sales.c.cliente_id.is_not(None))
    elif customer_type == "final_consumer":
        query = query.where(sales.c.cliente_id.is_(None))
    query = query.order_by(sales.c.fecha.asc())
    return [dict(row) for row in db.execute(query).mappings()]

def _analytics_tables(current_user: User) -> dict:
    return get_tenant_tables(get_user_schema_name(current_user))

def _risk_level(score: Decimal) -> str:
    if score >= Decimal("75"):
        return "critical"
    if score >= Decimal("50"):
        return "high"
    if score >= Decimal("25"):
        return "medium"
    if score > Decimal("0"):
        return "low"
    return "healthy"

def _bucket_start(value: datetime, window: AnalyticsWindow) -> date:
    value_date = value.date()
    if window == "day":
        return value_date
    if window == "week":
        return value_date - timedelta(days=value_date.weekday())
    return date(value_date.year, value_date.month, 1)

def _bucket_label(value: date, window: AnalyticsWindow) -> str:
    if window == "month":
        return value.strftime("%Y-%m")
    if window == "week":
        return f"{value.isoformat()} / {(value + timedelta(days=6)).isoformat()}"
    return value.isoformat()

def _decimal(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value or 0))

def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM)