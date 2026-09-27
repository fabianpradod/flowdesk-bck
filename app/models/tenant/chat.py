"""Private, expiring conversations inside each company's schema."""
import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.models.tenant.base import Base, TENANT_SCHEMA


class ChatConversation(Base):
    __tablename__ = "chat_conversation"
    __table_args__ = (
        Index("ix_chat_owner_recency", "usuario_id", "last_message_at", "id"),
        Index("ix_chat_expiry", "expires_at"),
        {"schema": TENANT_SCHEMA},
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    usuario_id = Column(UUID(as_uuid=True), ForeignKey("global.users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(120), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    last_message_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revision = Column(Integer, nullable=False, default=0)


class ChatMessage(Base):
    __tablename__ = "chat_message"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence", name="uq_chat_message_sequence"),
        CheckConstraint("role IN ('user', 'assistant')", name="ck_chat_message_role"),
        {"schema": TENANT_SCHEMA},
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey(f"{TENANT_SCHEMA}.chat_conversation.id", ondelete="CASCADE"), nullable=False)
    sequence = Column(Integer, nullable=False)
    role = Column(String(10), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    sources = Column(JSON, nullable=False, default=list)
    limitations = Column(JSON, nullable=False, default=list)
