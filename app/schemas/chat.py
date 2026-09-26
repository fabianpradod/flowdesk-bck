"""Public contract for private, expiring business conversations."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)
    conversation_id: UUID | None = None

    @field_validator("message", mode="before")
    @classmethod
    def trim_message(cls, value):
        return value.strip() if isinstance(value, str) else value


class ChatSource(BaseModel):
    """Built by the backend from executed tools, never by the LLM."""

    tool: str = Field(min_length=1, max_length=100)
    domain: Literal["inventory", "sales", "customers"]
    start_date: date | None = None
    end_date: date | None = None
    as_of: AwareDatetime
    filters: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_range(self):
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("Provide both dates or neither for a current snapshot")
        if self.start_date is not None and self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        return self


class ChatResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID
    answer: str = Field(min_length=1)
    created_at: AwareDatetime
    expires_at: AwareDatetime
    sources: list[ChatSource] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ConversationSummary(BaseModel):
    id: UUID
    title: str = Field(min_length=1, max_length=120)
    created_at: AwareDatetime
    last_message_at: AwareDatetime
    expires_at: AwareDatetime


class ConversationList(BaseModel):
    items: list[ConversationSummary]
    next_cursor: str | None = None


class ConversationMessage(BaseModel):
    id: UUID
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)
    created_at: AwareDatetime
    sources: list[ChatSource] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ConversationDetail(BaseModel):
    conversation: ConversationSummary
    messages: list[ConversationMessage]
    next_cursor: str | None = None
