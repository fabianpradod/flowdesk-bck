import json
from datetime import date
from decimal import Decimal
from uuid import uuid4
import pytest
from pydantic import ValidationError
from app.schemas.intelligence import IntelligentAnalysisRequest
from app.services import analysis_context, intelligence as intelligence_service
from app.utils.exceptions import AppError
from main import app

class FakeProvider:
    name = "fake-provider"

    def __init__(self, response=None):
        self.response = response or {
            "summary": "El inventario requiere seguimiento.",
            "insights": [
                {
                    "title": "Productos sin stock",
                    "description": "Hay dos productos sin existencias.",
                    "severity": "critical",
                }
            ],
            "recommendations": [
                {
                    "title": "Reabastecer",
                    "description": "Priorizar los productos con mayor riesgo.",
                    "priority": "high",
                }
            ],
        }
        self.request = None
        self.context = None

    def generate(self, *, request, context):
        self.request = request
        self.context = context
        return self.response

@pytest.fixture
def analysis_data(monkeypatch):
    metrics = {
        "period": "30d",
        "product_id": None,
        "start_date": date(2026, 8, 4),
        "end_date": date(2026, 9, 2),
        "entradas": Decimal("40"),
        "salidas": Decimal("15"),
        "stock_bajo": 3,
        "sin_stock": 2,
    }
    products = {
        "period": "30d",
        "sort_by": "stock_risk",
        "start_date": metrics["start_date"],
        "end_date": metrics["end_date"],
        "products": [
            {
                "product_id": "8ed237dd-67ea-4d9c-92f4-29439d0e0138",
                "sku": "SKU-1",
                "nombre": "Producto de riesgo",
                "stock_risk_score": Decimal("95"),
            }
        ],
    }
    trend = {
        "period": "30d",
        "window": "day",
        "product_id": None,
        "start_date": metrics["start_date"],
        "end_date": metrics["end_date"],
        "points": [
            {
                "period_start": metrics["end_date"],
                "period_label": "2026-09-02",
                "inbound_quantity": Decimal("5"),
                "outbound_quantity": Decimal("2"),
                "net_quantity": Decimal("3"),
                "movement_count": 2,
                "ending_stock": Decimal("20"),
            }
        ],
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
    return metrics, products, trend

def test_request_normalizes_question():
    request = IntelligentAnalysisRequest(question="  ¿Qué requiere atención?  ")

    assert request.question == "¿Qué requiere atención?"

def test_request_rejects_client_filter_for_final_consumer():
    with pytest.raises(ValidationError):
        IntelligentAnalysisRequest(
            client_id=uuid4(),
            customer_type="final_consumer",
        )

def test_provider_dependency_reports_not_configured(monkeypatch):
    monkeypatch.setattr(intelligence_service, "ZAI_API_KEY", None)

    with pytest.raises(AppError) as error:
        intelligence_service.get_analysis_provider()

    assert error.value.status_code == 503
    assert error.value.code == "ai_provider_unavailable"

def test_provider_dependency_builds_zai_provider(monkeypatch):
    monkeypatch.setattr(intelligence_service, "ZAI_API_KEY", "secret")
    monkeypatch.setattr(intelligence_service, "ZAI_MODEL", "test-model")
    monkeypatch.setattr(intelligence_service, "ZAI_BASE_URL", "https://zai.test/v4")
    monkeypatch.setattr(intelligence_service, "ZAI_TIMEOUT_SECONDS", 7)

    provider = intelligence_service.get_analysis_provider()

    assert provider.name == "zai:test-model"

def test_service_builds_sanitized_context(seed_test_db, analysis_data):
    current_user = next(
        user
        for users in seed_test_db.data.values()
        for user in users
        if getattr(user, "email", None) == "admin.demo@flowdesk.com"
    )
    provider = FakeProvider()

    result = intelligence_service.create_intelligent_analysis(
        IntelligentAnalysisRequest(question="Revisa el riesgo"),
        current_user,
        seed_test_db,
        provider,
    )

    assert result["provider"] == "fake-provider"
    assert result["analysis"].recommendations[0].priority == "high"
    assert provider.context["inventory_metrics"]["sin_stock"] == 2
    assert provider.context["inventory_metrics"]["net_movement"] == 25.0
    assert provider.context["inventory_trend"]["window"] == "day"
    assert provider.context["data_limitations"]
    assert "email" not in provider.context
    assert "username" not in provider.context
    assert "schema_name" not in provider.context
    json.dumps(provider.context)

def test_service_rejects_invalid_provider_response(seed_test_db, analysis_data):
    current_user = next(
        user
        for users in seed_test_db.data.values()
        for user in users
        if getattr(user, "email", None) == "admin.demo@flowdesk.com"
    )
    provider = FakeProvider(response={"summary": ""})

    with pytest.raises(AppError) as error:
        intelligence_service.create_intelligent_analysis(
            IntelligentAnalysisRequest(),
            current_user,
            seed_test_db,
            provider,
        )

    assert error.value.status_code == 502
    assert error.value.code == "invalid_ai_response"

def test_endpoint_requires_authentication(client):
    response = client.post("/api/v1/ai/analysis", json={})

    assert response.status_code == 401

def test_endpoint_returns_structured_analysis(admin_client, analysis_data):
    provider = FakeProvider()
    app.dependency_overrides[intelligence_service.get_analysis_provider] = lambda: provider

    try:
        response = admin_client.post(
            "/api/v1/ai/analysis",
            json={
                "period": "30d",
                "question": "¿Qué productos requieren atención?",
            },
        )
    finally:
        app.dependency_overrides.pop(intelligence_service.get_analysis_provider, None)

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "fake-provider"
    assert body["scope"] == "inventory"
    assert body["analysis"]["insights"][0]["severity"] == "critical"
    assert body["analysis"]["recommendations"][0]["priority"] == "high"

def test_endpoint_rejects_user_without_tenant(superadmin_client, analysis_data):
    app.dependency_overrides[intelligence_service.get_analysis_provider] = lambda: FakeProvider()

    try:
        response = superadmin_client.post("/api/v1/ai/analysis", json={})
    finally:
        app.dependency_overrides.pop(intelligence_service.get_analysis_provider, None)

    assert response.status_code == 403

def test_endpoint_rejects_invalid_filters_before_calling_provider(admin_client):
    app.dependency_overrides[intelligence_service.get_analysis_provider] = FakeProvider
    try:
        response = admin_client.post(
            "/api/v1/ai/analysis",
            json={"period": "invalid", "question": "Analiza"},
        )
    finally:
        app.dependency_overrides.pop(intelligence_service.get_analysis_provider, None)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"

def test_endpoint_preserves_provider_error_contract(admin_client, analysis_data):
    class UnavailableProvider(FakeProvider):
        def generate(self, *, request, context):
            raise AppError(
                status_code=503,
                message="The analysis provider rate limit was reached",
                code="ai_provider_rate_limited",
            )

    app.dependency_overrides[intelligence_service.get_analysis_provider] = UnavailableProvider
    try:
        response = admin_client.post("/api/v1/ai/analysis", json={})
    finally:
        app.dependency_overrides.pop(intelligence_service.get_analysis_provider, None)

    assert response.status_code == 503
    assert response.json()["code"] == "ai_provider_rate_limited"

def test_openapi_includes_intelligent_analysis_endpoint():
    schema = app.openapi()

    operation = schema["paths"]["/api/v1/ai/analysis"]["post"]
    assert operation["summary"] == "Generar análisis inteligente"
    assert "200" in operation["responses"]
    assert "503" in operation["responses"]