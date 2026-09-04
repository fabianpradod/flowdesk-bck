from decimal import Decimal
from typing import Any
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session
from app.models.users import User
from app.schemas.intelligence import IntelligentAnalysisRequest
from app.services import inventory as inventory_service
from app.services import analytics as analytics_service

MAX_RISK_PRODUCTS = 5
MAX_TREND_POINTS = 30

def build_business_context(
    request: IntelligentAnalysisRequest,
    current_user: User,
    db: Session,
) -> dict[str, Any]:
    """Prepare a bounded, tenant-scoped and PII-free context for an LLM."""
    include_inventory = request.scope in {"inventory", "catalog", "business"}
    include_sales = request.scope in {"sales", "business"}
    include_catalog = request.scope in {"catalog", "business"}
    trend_window = _trend_window(request)
    context = {
        "context_version": "2.0",
        "scope": request.scope,
        "available_domains": [],
        "filters": {
            "period": request.period,
            "start_date": request.start_date,
            "end_date": request.end_date,
            "product_id": request.product_id,
            "supplier_id": request.supplier_id,
            "client_id": request.client_id,
            "customer_type": request.customer_type,
        },
        "question": request.question,
        "data_limitations": [],
    }

    if include_inventory:
        metrics = inventory_service.get_inventory_metrics(
            current_user,
            db,
            period=request.period,
            product_id=request.product_id,
            start_date=request.start_date,
            end_date=request.end_date,
        )
        products = inventory_service.get_product_analytics(
            current_user,
            db,
            period=request.period,
            sort_by="stock_risk",
            limit=MAX_RISK_PRODUCTS,
            start_date=request.start_date,
            end_date=request.end_date,
        )
        trend = inventory_service.get_inventory_trend(
            current_user,
            db,
            period=request.period,
            window=trend_window,
            product_id=request.product_id,
            start_date=request.start_date,
            end_date=request.end_date,
        )
        entradas = Decimal(str(metrics["entradas"]))
        salidas = Decimal(str(metrics["salidas"]))
        context["available_domains"].append("inventory")
        context["filters"]["start_date"] = metrics["start_date"]
        context["filters"]["end_date"] = metrics["end_date"]
        context["inventory_metrics"] = {
            "entradas": entradas,
            "salidas": salidas,
            "net_movement": entradas - salidas,
            "stock_bajo": metrics["stock_bajo"],
            "sin_stock": metrics["sin_stock"],
            "products_requiring_attention": metrics["stock_bajo"] + metrics["sin_stock"],
        }
        context["products_at_risk"] = products["products"][:MAX_RISK_PRODUCTS]
        context["inventory_trend"] = {
            "window": trend_window,
            "points": trend["points"][-MAX_TREND_POINTS:],
        }

    if include_sales:
        sales_filters = {
            "period": request.period,
            "customer_type": request.customer_type,
            "client_id": request.client_id,
            "start_date": request.start_date,
            "end_date": request.end_date,
        }
        metrics = analytics_service.get_sales_metrics(current_user, db, **sales_filters)
        trend = analytics_service.get_sales_trend(
            current_user, db, window=trend_window, **sales_filters
        )
        top_products = analytics_service.get_top_selling_products(
            current_user,
            db,
            supplier_id=request.supplier_id,
            product_id=request.product_id,
            limit=MAX_RISK_PRODUCTS,
            **sales_filters,
        )
        context["available_domains"].append("sales")
        context["filters"]["start_date"] = metrics["start_date"]
        context["filters"]["end_date"] = metrics["end_date"]
        context["sales_metrics"] = metrics
        context["sales_trend"] = {
            "window": trend_window,
            "points": trend["points"][-MAX_TREND_POINTS:],
        }
        context["top_selling_products"] = top_products["products"][:MAX_RISK_PRODUCTS]

    if include_catalog:
        creation = analytics_service.get_product_creation_trend(
            current_user,
            db,
            period=request.period,
            window=trend_window,
            supplier_id=request.supplier_id,
            start_date=request.start_date,
            end_date=request.end_date,
        )
        context["available_domains"].append("catalog")
        context["catalog_creation_trend"] = {
            **creation,
            "points": creation["points"][-MAX_TREND_POINTS:],
        }

    if not include_sales:
        context["data_limitations"].append(
            "Sales, revenue and customer metrics were not requested for this scope."
        )
    context["data_limitations"].append(
        "Inventory outbound movements are not equivalent to confirmed sales."
    )
    return jsonable_encoder(context)

def _trend_window(request: IntelligentAnalysisRequest) -> str:
    if request.period in {"6m", "12m", "ytd"}:
        return "month"
    if request.period == "90d":
        return "week"
    if request.period == "custom" and request.start_date and request.end_date:
        days = (request.end_date - request.start_date).days
        if days > 180:
            return "month"
        if days > 31:
            return "week"
    return "day"