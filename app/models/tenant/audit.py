"""Append-only application events, stored inside the affected company's schema."""
from uuid import uuid4
from sqlalchemy import Column, DateTime, Index, String, text
from sqlalchemy import Uuid as UUID
from app.models.tenant.base import Base, TENANT_SCHEMA


class AuditEvent(Base):
    __tablename__ = 'audit_event'
    __table_args__ = (
        Index('ix_audit_event_occurred_id', 'occurred_at', 'id'),
        {'schema': TENANT_SCHEMA},
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    occurred_at = Column(DateTime, nullable=False, server_default=text('now()'))
    actor_id = Column(UUID(as_uuid=True), nullable=False)
    action = Column(String(80), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=False)
