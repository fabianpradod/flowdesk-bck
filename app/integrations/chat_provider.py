"""Internal provider boundary; these messages are never accepted from API clients."""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ChatCompletion:
    content: str | None
    tool_calls: tuple[ToolCall, ...]
    # Preserve the provider's assistant message for the next tool round, including
    # reasoning_content when present. Do not expose it in public responses/logs.
    assistant_message: dict[str, Any]


class ChatProvider(Protocol):
    name: str

    async def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        timeout_seconds: float | None = None,
    ) -> ChatCompletion: ...
