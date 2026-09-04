import json
import httpx
import pytest
from app.integrations.zai import ZAIAnalysisProvider
from app.schemas.intelligence import IntelligentAnalysisRequest
from app.utils.exceptions import AppError

VALID_ANALYSIS = {
    "summary": "Hay productos que requieren atención.",
    "insights": [
        {
            "title": "Riesgo de inventario",
            "description": "Un producto está agotado.",
            "severity": "critical",
        }
    ],
    "recommendations": [
        {
            "title": "Reabastecer",
            "description": "Revisar el producto agotado.",
            "priority": "high",
        }
    ],
}

def _provider(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return ZAIAnalysisProvider(
        api_key="test-secret-key",
        model="glm-5.3-flash",
        base_url="https://api.z.ai/api/paas/v4/",
        timeout_seconds=5,
        client=client,
    )

def test_zai_provider_sends_openai_compatible_structured_request():
    captured = {}

    def handler(request):
        captured["request"] = request
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(VALID_ANALYSIS)}}]},
        )

    provider = _provider(handler)
    result = provider.generate(
        request=IntelligentAnalysisRequest(question="¿Qué debo atender?"),
        context={"inventory_metrics": {"sin_stock": 1}},
    )

    sent_request = captured["request"]
    payload = captured["payload"]
    assert result == VALID_ANALYSIS
    assert sent_request.headers["authorization"] == "Bearer test-secret-key"
    assert "test-secret-key" not in str(sent_request.url)
    assert sent_request.url.path == "/api/paas/v4/chat/completions"
    assert payload["model"] == "glm-5.3-flash"
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["response_format"] == {"type": "json_object"}
    assert "sin_stock" in payload["messages"][1]["content"]

@pytest.mark.parametrize(
    ("status_code", "expected_status", "expected_code"),
    [
        (401, 503, "ai_provider_auth_error"),
        (403, 503, "ai_provider_auth_error"),
        (429, 503, "ai_provider_rate_limited"),
        (500, 502, "ai_provider_error"),
    ],
)
def test_zai_provider_maps_http_errors(status_code, expected_status, expected_code):
    provider = _provider(lambda _request: httpx.Response(status_code, json={"error": {}}))

    with pytest.raises(AppError) as error:
        provider.generate(request=IntelligentAnalysisRequest(), context={})

    assert error.value.status_code == expected_status
    assert error.value.code == expected_code

def test_zai_provider_maps_network_errors_to_unavailable():
    def handler(request):
        raise httpx.ConnectError("offline", request=request)

    provider = _provider(handler)

    with pytest.raises(AppError) as error:
        provider.generate(request=IntelligentAnalysisRequest(), context={})

    assert error.value.status_code == 503
    assert error.value.code == "ai_provider_unavailable"

@pytest.mark.parametrize(
    "body",
    [
        {"choices": []},
        {"choices": [{"message": {"content": "not-json"}}]},
        {"choices": [{"message": {"content": ""}}]},
    ],
)
def test_zai_provider_rejects_invalid_model_response(body):
    provider = _provider(lambda _request: httpx.Response(200, json=body))

    with pytest.raises(AppError) as error:
        provider.generate(request=IntelligentAnalysisRequest(), context={})

    assert error.value.status_code == 502
    assert error.value.code == "invalid_ai_response"