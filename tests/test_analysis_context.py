from datetime import date, timedelta
from decimal import Decimal
import json
import pytest
from app.schemas.intelligence import IntelligentAnalysisRequest
from app.services import analysis_context

def test_context_is_bounded_sanitized_and_json_safe(monkeypatch):
    end_date = date(2026, 9, 2)
    metrics = {
        "start_date": end_date - timedelta(days=30),
        "end_date": end_date,
        "entradas": Decimal("12.50"),
        "salidas": Decimal("7.25"),
        "stock_bajo": 2,
        "sin_stock": 1,
    }
    products = {"products": [{"product_id": str(index)} for index in range(10)]}
    trend = {
        "points": [
            {
                "period_start": end_date - timedelta(days=index),
                "net_quantity": Decimal(index),
            }
            for index in range(40)
        ]
    }
    monkeypatch.setattr(
        analysis_context.inventory_service,
        "get_inventory_metrics",
        lambda *_args, **_kwargs: metrics,
    )
    monkeypatch.setattr(
        analysis_context.inventory_service,
        "get_product_analytics",
        lambda *_args, **_kwargs: products,
    )
    monkeypatch.setattr(
        analysis_context.inventory_service,
        "get_inventory_trend",
        lambda *_args, **_kwargs: trend,
    )

    context = analysis_context.build_business_context(
        IntelligentAnalysisRequest(question="Analiza el inventario"),
        current_user=object(),
        db=object(),
    )

    assert context["context_version"] == "2.0"
    assert context["inventory_metrics"]["net_movement"] == 5.25
    assert context["inventory_metrics"]["products_requiring_attention"] == 3
    assert len(context["products_at_risk"]) == 5
    assert len(context["inventory_trend"]["points"]) == 30
    assert "email" not in context
    assert "company" not in context
    assert "schema_name" not in context
    json.dumps(context)

def test_business_context_combines_inventory_sales_and_catalog(monkeypatch):
    resolved_date = date(2026, 9, 2)
    monkeypatch.setattr(
        analysis_context.inventory_service,
        "get_inventory_metrics",
        lambda *_args, **_kwargs: {
            "start_date": resolved_date,
            "end_date": resolved_date,
            "entradas": 3,
            "salidas": 1,
            "stock_bajo": 0,
            "sin_stock": 0,
        },
    )
    monkeypatch.setattr(
        analysis_context.inventory_service,
        "get_product_analytics",
        lambda *_args, **_kwargs: {"products": []},
    )
    monkeypatch.setattr(
        analysis_context.inventory_service,
        "get_inventory_trend",
        lambda *_args, **_kwargs: {"points": []},
    )
    monkeypatch.setattr(
        analysis_context.analytics_service,
        "get_sales_metrics",
        lambda *_args, **_kwargs: {"start_date": resolved_date, "end_date": resolved_date, "net_sales": 25},
    )
    monkeypatch.setattr(
        analysis_context.analytics_service,
        "get_sales_trend",
        lambda *_args, **_kwargs: {"points": []},
    )
    monkeypatch.setattr(
        analysis_context.analytics_service,
        "get_top_selling_products",
        lambda *_args, **_kwargs: {"products": [{"sku": "SKU-1"}]},
    )
    monkeypatch.setattr(
        analysis_context.analytics_service,
        "get_product_creation_trend",
        lambda *_args, **_kwargs: {"total_created": 1, "points": []},
    )

    context = analysis_context.build_business_context(
        IntelligentAnalysisRequest(scope="business"), object(), object()
    )

    assert context["available_domains"] == ["inventory", "sales", "catalog"]
    assert context["sales_metrics"]["net_sales"] == 25
    assert context["top_selling_products"][0]["sku"] == "SKU-1"
    assert context["catalog_creation_trend"]["total_created"] == 1

@pytest.mark.parametrize(
    ("analysis_request", "expected"),
    [
        (IntelligentAnalysisRequest(period="7d"), "day"),
        (IntelligentAnalysisRequest(period="90d"), "week"),
        (IntelligentAnalysisRequest(period="12m"), "month"),
        (
            IntelligentAnalysisRequest(
                period="custom",
                start_date=date(2026, 1, 1),
                end_date=date(2026, 3, 1),
            ),
            "week",
        ),
        (
            IntelligentAnalysisRequest(
                period="custom",
                start_date=date(2025, 1, 1),
                end_date=date(2026, 1, 1),
            ),
            "month",
        ),
    ],
)
def test_trend_window_adapts_to_period(analysis_request, expected):
    assert analysis_context._trend_window(analysis_request) == expected