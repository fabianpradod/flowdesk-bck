"""Opt-in network smoke test using synthetic data only; never part of normal CI."""

import asyncio
import json
import os
from uuid import uuid4

import pytest

from app.api.dependencies.ai import get_chat_provider
from app.core import config


@pytest.mark.skipif(
    os.getenv("RUN_ZAI_INTEGRATION_TEST") != "1" or not (config.ZAI_API_KEY or "").strip(),
    reason="requires RUN_ZAI_INTEGRATION_TEST=1 and ZAI_API_KEY in environment/.env",
)
def test_live_chat_tool_round_trip():
    async def run():
        provider = get_chat_provider()
        messages = [
            {"role": "system", "content": (
                "You are testing a business assistant with synthetic data. "
                "Call sales_metrics exactly once with period 30d before answering. "
                "After receiving the result, report its net_sales and sales_count "
                "in Spanish and copy its verification_code exactly into your answer."
            )},
            {"role": "user", "content": "Consulta las ventas de los últimos 30 días."},
        ]
        tools = [{"type": "function", "function": {
            "name": "sales_metrics",
            "description": "Retrieve synthetic sales metrics for this integration test.",
            "parameters": {
                "type": "object",
                "properties": {"period": {"type": "string", "enum": ["30d"]}},
                "required": ["period"],
                "additionalProperties": False,
            },
        }}]
        first = await provider.complete(messages=messages, tools=tools)
        assert len(first.tool_calls) == 1, "Model did not request the expected tool"
        call = first.tool_calls[0]
        assert call.name == "sales_metrics"
        assert call.arguments == {"period": "30d"}

        # Generated after the first call: the answer can only learn this value
        # from the tool result, not from the initial prompt or prior knowledge.
        verification_code = f"flowdesk-{uuid4().hex}"
        messages.extend([
            first.assistant_message,
            {"role": "tool", "tool_call_id": call.id, "content": json.dumps({
                "net_sales": "1250.00", "sales_count": 5,
                "verification_code": verification_code,
            })},
        ])
        final = await provider.complete(messages=messages, tools=[])
        assert not final.tool_calls
        assert final.content and verification_code in final.content, "Answer did not use the tool result"
        normalized = final.content.replace(",", "").replace(".", "").replace(" ", "")
        assert "1250" in normalized, "Answer did not include the returned sales total"
        # Only synthetic final text is printed. Never log request headers,
        # credentials, raw responses, or the internal reasoning transcript.
        print(f"\nProvider: {provider.name}\nTool: {call.name}\nAnswer: {final.content}")

    asyncio.run(run())
