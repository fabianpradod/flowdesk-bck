from decimal import Decimal
from typing import Any
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session
from app.models.users import User
from app.schemas.intelligence import IntelligentAnalysisRequest
from app.services import inventory as inventory_service

MAX_RISK_PRODUCTS = 5
MAX_TREND_POINTS = 30

def build_business_context(
    request: IntelligentAnalysisRequest,
    current_user: User,
    db: Session,
) -> dict[str, Any]:
    """Prepare a bounded, tenant-scoped and PII-free context for an LLM."""
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
    trend_window = _trend_window(request)
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
    context = {
        "context_version": "1.0",
        "scope": request.scope,
        "available_domains": ["inventory"],
        "filters": {
            "period": request.period,
            "start_date": metrics["start_date"],
            "end_date": metrics["end_date"],
            "product_id": request.product_id,
        },
        "question": request.question,
        "inventory_metrics": {
            "entradas": entradas,
            "salidas": salidas,
            "net_movement": entradas - salidas,
            "stock_bajo": metrics["stock_bajo"],
            "sin_stock": metrics["sin_stock"],
            "products_requiring_attention": metrics["stock_bajo"] + metrics["sin_stock"],
        },
        "products_at_risk": products["products"][:MAX_RISK_PRODUCTS],
        "inventory_trend": {
            "window": trend_window,
            "points": trend["points"][-MAX_TREND_POINTS:],
        },
        "data_limitations": [
            "Sales, revenue, profit and customer metrics are not available in this context.",
            "Inventory outbound movements are not equivalent to confirmed sales.",
        ],
    }
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