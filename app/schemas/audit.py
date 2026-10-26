from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class AuditEventResponse(BaseModel):
    id: UUID
    occurred_at: datetime
    actor_id: UUID
    action: str
    entity_type: str
    entity_id: UUID


class AuditPage(BaseModel):
    items: list[AuditEventResponse]
    next_cursor: str | None = None
