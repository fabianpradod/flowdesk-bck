"""Approved aggregate queries. The model can choose filters, never SQL or a tenant."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import case, func, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.schemas.chat import ChatSource
from app.services.analytics import FINAL_SALE_STATES
from app.services.chat_store import ChatActor, utcnow
from app.tenancy.runtime import get_tenant_tables
from app.utils.exceptions import AppError


class EmptyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RangeArgs(EmptyArgs):
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def paired_dates(self):
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("Provide both dates or neither")
        if self.start_date and (self.end_date < self.start_date or (self.end_date - self.start_date).days >= 366):
            raise ValueError("Date range must contain between 1 and 366 days")
        return self


class RankedArgs(RangeArgs):
    limit: int = Field(default=20, ge=1, le=50, strict=True)


class CustomerArgs(RankedArgs):
    customer_id: UUID | None = None


class ProductArgs(EmptyArgs):
    limit: int = Field(default=20, ge=1, le=50, strict=True)
    stock_status: Literal["all", "low", "out_of_stock"] = "low"
    sku: str | None = Field(default=None, min_length=1, max_length=50)


DEFINITIONS = {
    "inventory_metrics": (EmptyArgs, "inventory", "Current active inventory: product counts, stockouts, low-stock counts and retail stock value. Current snapshot, not historical stock."),
    "inventory_products": (ProductArgs, "inventory", "Current active products, optionally by exact SKU or stock status, ordered by shortage then SKU. Bounded results; includes product IDs, SKU, units and stock thresholds."),
    "inventory_trend": (RangeArgs, "inventory", "Inventory movements by date: recorded units in/out and net stock change. Not historical stock balances. Default last 30 UTC calendar days; maximum 366 days."),
    "sales_metrics": (RangeArgs, "sales", "Finalized sales totals: gross subtotal, discounts, tax, net sales including tax, count and average ticket. Default last 30 UTC calendar days; maximum 366 days."),
    "sales_trend": (RangeArgs, "sales", "Finalized sales count and net sales by date. Default last 30 UTC calendar days; maximum 366 days."),
    "top_products": (RankedArgs, "sales", "Products ranked by finalized sale-line revenue (before sale-level discounts/tax), with quantities. Default last 30 UTC days; maximum 366 days."),
    "customer_purchases": (CustomerArgs, "customers", "Customer IDs and purchase metrics only, ranked by finalized net sales. Optional exact customer UUID; excludes anonymous sales. Default last 30 UTC days; maximum 366 days."),
}


def tool_definitions():
    return [{"type": "function", "function": {"name": name, "description": description,
             "parameters": args.model_json_schema()}} for name, (args, _, description) in DEFINITIONS.items()]


def json_value(value):
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Unsupported tool value: {type(value).__name__}")


@dataclass(frozen=True)
class ToolResult:
    content: str
    source: ChatSource
    limitations: list[str]


class BusinessTools:
    def __init__(self, db, actor: ChatActor):
        self.db = db
        self.tables = get_tenant_tables(actor.schema_name)

    def execute(self, name, arguments, *, timeout_seconds=5, now=None):
        if name not in DEFINITIONS:
            raise AppError(422, "Tool is not allowed", "invalid_tool_arguments")
        model, domain, _ = DEFINITIONS[name]
        try:
            args = model.model_validate(arguments)
        except ValidationError as exc:
            # Do not echo arbitrary arguments or Pydantic input values to the model.
            raise AppError(422, "Invalid tool filters; use the advertised schema and a range of at most 366 days", "invalid_tool_arguments") from exc
        now = now or utcnow()
        start = end = None
        if isinstance(args, RangeArgs):
            end = args.end_date or now.date()
            start = args.start_date or (end - timedelta(days=29))
            if end > now.date():
                raise AppError(422, "Future dates are not supported", "invalid_tool_arguments")
        try:
            if self.db.get_bind().dialect.name == "postgresql":
                # SET LOCAL lasts only until rollback; every tool releases its read transaction.
                self.db.execute(text("SET TRANSACTION READ ONLY"))
                self.db.execute(text("SELECT set_config('statement_timeout', :timeout, true)"),
                                {"timeout": str(max(1, int(min(timeout_seconds, 5) * 1000)))})
            data, limitations = self._query(name, args, start, end)
            content = json.dumps(data, default=json_value, ensure_ascii=False, allow_nan=False)
            if len(content) > 24000:
                raise AppError(502, "Tool result exceeded its size limit", "ai_tool_result_too_large")
            source = ChatSource(tool=name, domain=domain, start_date=start, end_date=end, as_of=now,
                                filters=args.model_dump(mode="json", exclude_none=True))
            return ToolResult(content, source, limitations)
        except SQLAlchemyError as exc:
            raise AppError(503, "Business data is temporarily unavailable", "ai_data_unavailable") from exc
        finally:
            self.db.rollback()

    def _rows(self, query):
        return [dict(row) for row in self.db.execute(query).mappings()]

    def _query(self, name, args, start, end):
        p = self.tables["producto"].c
        v = self.tables["venta"].c
        d = self.tables["detalle_venta"].c
        m = self.tables["movimiento_inventario"].c
        limitations = []
        if name.startswith("inventory_"):
            limitations.append("Inventory quantities can use different units; do not add incompatible units.")
        if name == "inventory_metrics":
            q = select(func.count().label("active_products"),
                       func.sum(case((p.stock_actual == 0, 1), else_=0)).label("out_of_stock"),
                       func.sum(case((p.stock_actual < p.stock_minimo, 1), else_=0)).label("below_minimum"),
                       func.coalesce(func.sum(p.stock_actual * p.precio_venta), 0).label("retail_stock_value")
                       ).where(p.is_active.is_(True))
            limitations.append("Stock is a current snapshot. Retail stock value uses selling prices, not cost or profit.")
            result = self._rows(q)[0]
            result["out_of_stock"] = result["out_of_stock"] or 0
            result["below_minimum"] = result["below_minimum"] or 0
            return result, limitations
        if name == "inventory_products":
            q = select(p.id.label("product_id"), p.sku, p.nombre.label("product_name"), p.stock_actual.label("stock"),
                       p.stock_minimo.label("minimum_stock"), p.unidad_medida.label("unit"),
                       p.precio_venta.label("sale_price")).where(p.is_active.is_(True))
            if args.stock_status == "low":
                q = q.where(p.stock_actual < p.stock_minimo)
            elif args.stock_status == "out_of_stock":
                q = q.where(p.stock_actual == 0)
            if args.sku:
                q = q.where(p.sku == args.sku)
            rows = self._rows(q.order_by((p.stock_minimo - p.stock_actual).desc(), p.sku).limit(args.limit + 1))
            limitations.append("Stock is current; shortage ordering is not a demand forecast.")
            return self._ranked(rows, args.limit, limitations)
        lower = datetime.combine(start, time.min)
        upper = datetime.combine(end + timedelta(days=1), time.min)
        sales_filter = (v.fecha >= lower, v.fecha < upper, v.estado.in_(sorted(FINAL_SALE_STATES)))
        if name == "inventory_trend":
            delta = m.stock_resultante - m.stock_anterior
            q = select(func.date(m.fecha).label("date"),
                       func.sum(case((delta > 0, delta), else_=0)).label("units_in"),
                       func.sum(case((delta < 0, -delta), else_=0)).label("units_out"),
                       func.sum(delta).label("net_change")
                       ).where(m.fecha >= lower, m.fecha < upper).group_by(func.date(m.fecha)).order_by(func.date(m.fecha))
            limitations.append("Movement totals include adjustments and inactive products; they are not historical stock balances or exclusively sales demand.")
            return self._trend(self._rows(q), start, end), limitations
        limitations.append("Only finalized sales are included; net sales include sale-level discounts and tax. Currency is the company's recorded currency; no conversion is applied.")
        if name == "sales_metrics":
            q = select(func.count().label("sales_count"),
                       *[func.coalesce(func.sum(col), 0).label(label) for col, label in
                         [(v.subtotal, "gross_sales"), (v.descuento, "discounts"), (v.impuesto, "tax"), (v.total, "net_sales")]],
                       func.coalesce(func.avg(v.total), 0).label("average_ticket")
                       ).where(*sales_filter)
            return self._rows(q)[0], limitations
        if name == "sales_trend":
            q = select(func.date(v.fecha).label("date"), func.count().label("sales_count"),
                       func.sum(v.total).label("net_sales")).where(*sales_filter).group_by(func.date(v.fecha)).order_by(func.date(v.fecha))
            return self._trend(self._rows(q), start, end), limitations
        if name == "top_products":
            revenue = func.sum(d.subtotal)
            q = select(p.id.label("product_id"), p.sku, p.nombre.label("product_name"), p.unidad_medida.label("unit"),
                       func.sum(d.cantidad).label("quantity"), revenue.label("line_revenue")
                       ).select_from(self.tables["detalle_venta"].join(self.tables["venta"], d.venta_id == v.id)
                                     .join(self.tables["producto"], d.producto_id == p.id))
            q = q.where(*sales_filter).group_by(p.id, p.sku, p.nombre, p.unidad_medida).order_by(revenue.desc(), p.id).limit(args.limit + 1)
            limitations.append("Product revenue is the sale-line subtotal before sale-level discounts and tax, including products now inactive.")
            return self._ranked(self._rows(q), args.limit, limitations)
        # No join to cliente: its identifying columns cannot enter this projection.
        revenue = func.sum(v.total)
        q = select(v.cliente_id.label("customer_id"), func.count().label("purchase_count"),
                   revenue.label("net_sales"), func.avg(v.total).label("average_ticket"),
                   func.max(v.fecha).label("last_purchase_at")).where(*sales_filter, v.cliente_id.is_not(None))
        if args.customer_id:
            q = q.where(v.cliente_id == args.customer_id)
        q = q.group_by(v.cliente_id).order_by(revenue.desc(), v.cliente_id).limit(args.limit + 1)
        limitations.append("Customers are identified only by ID. Anonymous purchases are excluded; metrics refer only to the selected period.")
        return self._ranked(self._rows(q), args.limit, limitations)

    @staticmethod
    def _ranked(rows, limit, limitations):
        truncated = len(rows) > limit
        if truncated:
            limitations.append(f"Results are limited to the first {limit} matching entries.")
        return {"items": rows[:limit], "truncated": truncated}, limitations

    @staticmethod
    def _trend(rows, start, end):
        # SQL returns at most 366 daily aggregates, never raw business records.
        monthly = (end - start).days >= 60
        buckets = {}
        for row in rows:
            key = str(row["date"])[:7] if monthly else str(row["date"])
            bucket = buckets.setdefault(key, {"period": key})
            for name, value in row.items():
                if name != "date":
                    bucket[name] = bucket.get(name, 0) + value
        return {"granularity": "month" if monthly else "day", "items": list(buckets.values()),
                "missing_periods": "Periods without recorded activity are omitted; partial boundary months are possible."}
