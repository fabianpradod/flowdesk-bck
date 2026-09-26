from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.chat import ChatRequest, ChatResponse, ChatSource, ConversationMessage


def test_client_can_only_submit_a_message_and_optional_conversation_id():
    conversation_id = uuid4()
    request = ChatRequest(message="  ¿Y el mes pasado?  ", conversation_id=conversation_id)
    assert request.message == "¿Y el mes pasado?"
    assert request.conversation_id == conversation_id
    for field in ("tenant_id", "user_id", "history", "tools", "system_prompt"):
        with pytest.raises(ValidationError):
            ChatRequest.model_validate({"message": "Hola", field: "injected"})


@pytest.mark.parametrize("message", ["", " \n ", "x" * 4001, None, 123])
def test_invalid_message_is_rejected(message):
    with pytest.raises(ValidationError):
        ChatRequest(message=message)


def test_complete_reply_serializes_sources_and_retention_dates():
    now = datetime.now(timezone.utc)
    reply = ChatResponse(
        conversation_id=uuid4(), message_id=uuid4(), answer="Ventas: 100",
        created_at=now, expires_at=now + timedelta(days=15),
        sources=[ChatSource(
            tool="sales_metrics", domain="sales", as_of=now,
            start_date="2026-09-01", end_date="2026-09-25",
            filters={"client_id": str(uuid4())},
        )], limitations=["No se incluyen ventas en borrador."],
    )
    decoded = ChatResponse.model_validate_json(reply.model_dump_json())
    assert decoded == reply
    assert decoded.expires_at - decoded.created_at == timedelta(days=15)


def test_source_rejects_ambiguous_or_reversed_date_ranges():
    for dates in ({"start_date": "2026-09-01"}, {"start_date": "2026-09-25", "end_date": "2026-09-01"}):
        with pytest.raises(ValidationError):
            ChatSource(tool="sales_metrics", domain="sales", as_of=datetime.now(timezone.utc), **dates)


def test_public_history_cannot_contain_system_or_tool_messages():
    for role in ("system", "tool"):
        with pytest.raises(ValidationError):
            ConversationMessage(id=uuid4(), role=role, content="private", created_at=datetime.now(timezone.utc))
