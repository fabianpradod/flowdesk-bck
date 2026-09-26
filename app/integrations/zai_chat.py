"""One bounded Z.AI chat request. Tool execution belongs to the chat service."""

import asyncio
import json
import math
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.integrations.chat_provider import ChatCompletion, ToolCall
from app.utils.exceptions import AppError


def _invalid_response() -> AppError:
    return AppError(502, "The chat provider returned an invalid response", "invalid_ai_response")


def _reject_json_constant(value: str):
    raise ValueError(f"Non-finite JSON number: {value}")


class ZAIChatProvider:
    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        base_url: str,
        timeout_seconds: float,
        max_tokens: int = 4096,
        client: httpx.AsyncClient | None = None,
    ):
        if not api_key or not api_key.strip():
            raise AppError(503, "Chat provider is not configured", "ai_provider_unavailable")
        try:
            url = urlsplit(base_url)
            # Accessing port also validates malformed/out-of-range URL ports.
            port = url.port
            valid_url = (
                url.scheme == "https" and bool(url.hostname)
                and url.username is None and url.password is None
                and not url.query and not url.fragment
                and (port is None or port > 0)
            )
            valid_limits = (
                math.isfinite(timeout_seconds) and 0 < timeout_seconds <= 120
                and isinstance(max_tokens, int) and not isinstance(max_tokens, bool)
                and 512 <= max_tokens <= 8192
            )
        except (TypeError, ValueError):
            valid_url = valid_limits = False
        if not valid_url or not valid_limits or not model.strip():
            raise AppError(503, "Chat provider configuration is invalid", "ai_provider_misconfigured")
        self._api_key = api_key.strip()
        self._model = model.strip()
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_tokens = max_tokens
        self._client = client
        self.name = f"zai:{self._model}"

    async def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        timeout_seconds: float | None = None,
    ) -> ChatCompletion:
        budget = self._timeout_seconds
        if timeout_seconds is not None:
            if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
                raise AppError(504, "The chat provider timed out", "ai_provider_timeout")
            budget = min(budget, timeout_seconds)
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "thinking": {"type": "enabled"},
            "reasoning_effort": "low",
            "max_tokens": self._max_tokens,
        }
        if tools:
            payload.update(tools=tools, tool_choice="auto")
        try:
            # httpx timeouts apply to individual I/O operations; asyncio also
            # bounds the complete exchange when the caller has less time left.
            async with asyncio.timeout(budget):
                if self._client is not None:
                    response = await self._post(self._client, payload, budget)
                else:
                    async with httpx.AsyncClient() as client:
                        response = await self._post(client, payload, budget)
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise AppError(504, "The chat provider timed out", "ai_provider_timeout") from exc
        except httpx.RequestError as exc:
            raise AppError(503, "The chat provider is unavailable", "ai_provider_unavailable") from exc

        self._check_status(response)
        return self._parse(response, {tool["function"]["name"] for tool in tools})

    async def _post(
        self, client: httpx.AsyncClient, payload: dict[str, Any], budget: float,
    ) -> httpx.Response:
        return await client.post(
            f"{self._base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json=payload,
            timeout=budget,
            follow_redirects=False,
        )

    @staticmethod
    def _check_status(response: httpx.Response) -> None:
        status = response.status_code
        if status == 200:
            return
        if status in {401, 403}:
            raise AppError(503, "Chat provider credentials are invalid", "ai_provider_auth_error")
        if status == 429:
            # Z.AI uses HTTP 429 for both throttling and missing API credit.
            # Inspect only the known code; never expose the upstream body.
            try:
                code = str(response.json().get("error", {}).get("code"))
            except (ValueError, AttributeError, TypeError):
                code = None
            if code == "1113":
                raise AppError(503, "Chat provider API credit is unavailable", "ai_provider_quota_exhausted")
            raise AppError(503, "The chat provider rate limit was reached", "ai_provider_rate_limited")
        if status in {408, 504}:
            raise AppError(504, "The chat provider timed out", "ai_provider_timeout")
        if status == 503:
            raise AppError(503, "The chat provider is unavailable", "ai_provider_unavailable")
        # Do not forward upstream bodies, URLs, credentials, or redirect targets.
        raise AppError(502, "The chat provider returned an error", "ai_provider_error")

    @staticmethod
    def _parse(response: httpx.Response, allowed_tools: set[str]) -> ChatCompletion:
        try:
            choice = response.json()["choices"][0]
            finish_reason = choice["finish_reason"]
            if finish_reason == "length":
                raise AppError(502, "The chat provider response was truncated", "ai_response_truncated")
            if finish_reason == "content_filter":
                raise AppError(502, "The chat provider could not answer this request", "ai_response_filtered")
            if finish_reason not in {"stop", "tool_calls"}:
                raise ValueError("Unexpected finish reason")
            message = choice["message"]
            if message["role"] != "assistant":
                raise ValueError("Unexpected role")
            content = message.get("content")
            if content is not None and not isinstance(content, str):
                raise ValueError("Invalid content")
            raw_calls = message.get("tool_calls")
            if raw_calls is None:
                raw_calls = []
            if not isinstance(raw_calls, list) or len(raw_calls) > 8:
                raise ValueError("Invalid tool calls")
            calls = []
            ids = set()
            for raw in raw_calls:
                call_id = raw["id"]
                function = raw["function"]
                name, arguments = function["name"], function["arguments"]
                if (
                    raw["type"] != "function" or not isinstance(call_id, str)
                    or not call_id.strip() or len(call_id) > 200 or call_id in ids
                    or not isinstance(name, str) or name not in allowed_tools
                    or not isinstance(arguments, str) or len(arguments) > 16000
                ):
                    raise ValueError("Invalid tool call")
                parsed = json.loads(arguments, parse_constant=_reject_json_constant)
                if not isinstance(parsed, dict):
                    raise ValueError("Tool arguments must be an object")
                calls.append(ToolCall(call_id, name, parsed))
                ids.add(call_id)
            if not calls and (finish_reason == "tool_calls" or not content or not content.strip()):
                raise ValueError("Empty completion")
            reasoning = message.get("reasoning_content")
            if reasoning is not None and not isinstance(reasoning, str):
                raise ValueError("Invalid reasoning content")
            assistant_message = {"role": "assistant", "content": content}
            if calls:
                assistant_message["tool_calls"] = [
                    {"id": call.id, "type": "function", "function": {
                        "name": call.name, "arguments": raw["function"]["arguments"],
                    }}
                    for call, raw in zip(calls, raw_calls)
                ]
            if reasoning is not None:
                assistant_message["reasoning_content"] = reasoning
            return ChatCompletion(content, tuple(calls), assistant_message)
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
            raise _invalid_response() from exc
