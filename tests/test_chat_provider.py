import asyncio
import json

import httpx
import pytest

from app.api.dependencies.ai import get_chat_provider
from app.core import config
from app.integrations.zai_chat import ZAIChatProvider
from app.utils.exceptions import AppError, build_error_payload


TOOLS = [{"type": "function", "function": {
    "name": "sales_metrics",
    "description": "Read sales totals",
    "parameters": {"type": "object", "properties": {"period": {"type": "string"}}},
}}]
CALL = {"id": "call_1", "type": "function", "function": {
    "name": "sales_metrics", "arguments": '{"period":"30d"}',
}}


def response_body(content="Ventas: 100", *, calls=None, finish="stop", **extra):
    return {"choices": [{"finish_reason": finish, "message": {
        "role": "assistant", "content": content, "tool_calls": calls, **extra,
    }}]}


def provider(client, **kwargs):
    return ZAIChatProvider(
        api_key="test-secret-key", model="glm-5.3-flash",
        base_url="https://api.z.ai/api/paas/v4/", timeout_seconds=2,
        client=client, **kwargs,
    )


def complete_with(handler, *, tools=TOOLS, **kwargs):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await provider(client).complete(
                messages=[{"role": "user", "content": "¿Cuánto vendimos?"}],
                tools=tools, **kwargs,
            )
    return asyncio.run(run())


def test_tool_round_trip_preserves_assistant_protocol_and_reasoning():
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, json=response_body(
                None, calls=[CALL], finish="tool_calls", reasoning_content="internal reasoning",
            ))
        return httpx.Response(200, json=response_body())

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = provider(client)
            messages = [{"role": "user", "content": "¿Cuánto vendimos?"}]
            first = await adapter.complete(messages=messages, tools=TOOLS)
            assert first.content is None
            assert first.tool_calls[0].arguments == {"period": "30d"}
            messages += [first.assistant_message, {
                "role": "tool", "tool_call_id": first.tool_calls[0].id,
                "content": '{"net_sales":"100.00"}',
            }]
            final = await adapter.complete(messages=messages, tools=TOOLS)
            assert final.content == "Ventas: 100"
            assert final.tool_calls == ()
    asyncio.run(run())
    first_payload = json.loads(requests[0].content)
    second_payload = json.loads(requests[1].content)
    assert first_payload["tools"] == TOOLS
    assert first_payload["tool_choice"] == "auto"
    assert first_payload["model"] == "glm-5.3-flash"
    assert first_payload["stream"] is False
    assert first_payload["thinking"] == {"type": "enabled"}
    assert first_payload["reasoning_effort"] == "low"
    assert first_payload["max_tokens"] == 4096
    assert "response_format" not in first_payload
    assert second_payload["messages"][1]["reasoning_content"] == "internal reasoning"
    assert second_payload["messages"][1]["tool_calls"] == [CALL]
    assert requests[0].headers["authorization"] == "Bearer test-secret-key"
    assert "test-secret-key" not in str(requests[0].url)


def test_plain_answer_without_tools_does_not_advertise_tools():
    def handler(request):
        payload = json.loads(request.content)
        assert "tools" not in payload and "tool_choice" not in payload
        return httpx.Response(200, json=response_body())
    assert complete_with(handler, tools=[]).content == "Ventas: 100"


@pytest.mark.parametrize("body", [
    {}, {"choices": []}, {"choices": [{"message": {}}]},
    response_body(" "), response_body(123), response_body(finish="unexpected"),
    response_body(finish="tool_calls"),
    response_body(calls=[{**CALL, "function": {"name": "delete_sales", "arguments": "{}"}}]),
    response_body(calls=[{**CALL, "function": {"name": "sales_metrics", "arguments": "[]"}}]),
    response_body(calls=[{**CALL, "function": {"name": "sales_metrics", "arguments": '{"a":NaN}'}}]),
    response_body(calls=[{**CALL, "function": {"name": "sales_metrics", "arguments": "{broken"}}]),
    response_body(calls=[CALL, CALL]), response_body(calls=[CALL] * 9),
    response_body(calls="bad"), response_body(calls={}), response_body(calls=False),
    response_body(reasoning_content=[]),
])
def test_invalid_provider_responses_never_reach_tool_execution(body):
    with pytest.raises(AppError) as error:
        complete_with(lambda _: httpx.Response(200, json=body))
    assert (error.value.status_code, error.value.code) == (502, "invalid_ai_response")


@pytest.mark.parametrize(("finish", "code"), [
    ("length", "ai_response_truncated"), ("content_filter", "ai_response_filtered"),
])
def test_partial_or_filtered_answers_are_not_reported_as_success(finish, code):
    with pytest.raises(AppError) as error:
        complete_with(lambda _: httpx.Response(200, json=response_body(finish=finish)))
    assert error.value.code == code


@pytest.mark.parametrize(("status", "expected", "code"), [
    (401, 503, "ai_provider_auth_error"), (403, 503, "ai_provider_auth_error"),
    (429, 503, "ai_provider_rate_limited"), (500, 502, "ai_provider_error"),
    (503, 503, "ai_provider_unavailable"), (504, 504, "ai_provider_timeout"),
    (408, 504, "ai_provider_timeout"), (302, 502, "ai_provider_error"),
])
def test_upstream_errors_are_sanitized_without_retry_or_redirect(status, expected, code):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(status, text="secret-upstream-body", headers={
            "Location": "https://unexpected.example/collect",
        })
    with pytest.raises(AppError) as error:
        complete_with(handler)
    assert (error.value.status_code, error.value.code) == (expected, code)
    assert len(seen) == 1
    assert "secret" not in json.dumps(build_error_payload(error.value))


def test_invalid_json_is_a_sanitized_provider_failure():
    with pytest.raises(AppError) as error:
        complete_with(lambda _: httpx.Response(200, text="upstream invalid JSON"))
    assert error.value.code == "invalid_ai_response"


@pytest.mark.parametrize("code", ["1113", 1113])
def test_missing_api_credit_is_not_misreported_as_temporary_throttling(code):
    with pytest.raises(AppError) as error:
        complete_with(lambda _: httpx.Response(429, json={"error": {
            "code": code, "message": "private upstream billing details",
        }}))
    assert (error.value.status_code, error.value.code) == (503, "ai_provider_quota_exhausted")
    assert "private" not in json.dumps(build_error_payload(error.value))


@pytest.mark.parametrize("exception", [httpx.ReadTimeout, httpx.ConnectError])
def test_network_failures_are_classified(exception):
    def handler(request):
        raise exception("secret transport details", request=request)
    with pytest.raises(AppError) as error:
        complete_with(handler)
    expected = "ai_provider_timeout" if exception is httpx.ReadTimeout else "ai_provider_unavailable"
    assert error.value.code == expected
    assert "secret" not in json.dumps(build_error_payload(error.value))


def test_remaining_budget_cancels_the_entire_exchange():
    cancelled = []

    async def handler(request):
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.append(True)
        return httpx.Response(200, json=response_body())
    with pytest.raises(AppError) as error:
        complete_with(handler, timeout_seconds=0.01)
    assert error.value.code == "ai_provider_timeout"
    assert cancelled == [True]


def test_exhausted_budget_does_not_send_request():
    def handler(request):
        pytest.fail("An expired request must not reach the provider")
    with pytest.raises(AppError) as error:
        complete_with(handler, timeout_seconds=0)
    assert error.value.code == "ai_provider_timeout"


def test_caller_cannot_extend_the_configured_timeout():
    def handler(request):
        assert request.extensions["timeout"]["read"] == 2
        return httpx.Response(200, json=response_body())
    assert complete_with(handler, timeout_seconds=60).content == "Ventas: 100"


def test_provider_configuration_is_lazy_and_validated(monkeypatch):
    monkeypatch.setattr(config, "ZAI_API_KEY", None)
    with pytest.raises(AppError) as error:
        get_chat_provider()
    assert error.value.code == "ai_provider_unavailable"
    monkeypatch.setattr(config, "ZAI_API_KEY", "test-key")
    monkeypatch.setattr(config, "ZAI_CHAT_MAX_TOKENS", "typo")
    with pytest.raises(AppError) as error:
        get_chat_provider()
    assert error.value.code == "ai_provider_misconfigured"
    monkeypatch.setattr(config, "ZAI_CHAT_MAX_TOKENS", "4096")
    monkeypatch.setattr(config, "ZAI_BASE_URL", "https://api.z.ai/api/paas/v4")
    monkeypatch.setattr(config, "ZAI_MODEL", "glm-5.3-flash")
    monkeypatch.setattr(config, "ZAI_TIMEOUT_SECONDS", 30)
    assert get_chat_provider().name == "zai:glm-5.3-flash"


@pytest.mark.parametrize("changes", [
    {"base_url": "http://api.z.ai/v4"},
    {"base_url": "https://user:password@api.z.ai/v4"},
    {"base_url": "https://api.z.ai/v4?key=secret"},
    {"base_url": "https://api.z.ai:invalid/v4"},
    {"timeout_seconds": float("nan")}, {"timeout_seconds": -1},
    {"max_tokens": 0}, {"model": " "},
])
def test_invalid_config_fails_before_any_network_call(changes):
    settings = dict(api_key="key", model="glm-5.3-flash", base_url="https://api.z.ai/v4", timeout_seconds=30)
    with pytest.raises(AppError) as error:
        ZAIChatProvider(**(settings | changes))
    assert error.value.code == "ai_provider_misconfigured"
