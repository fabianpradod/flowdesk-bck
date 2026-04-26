import uuid

from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, text, Boolean
from app.models.user_permissions import user_permissions
from app.core.database import Base

class User(Base):
    __tablename__  = "users"
    __table_args__ = {"schema": "global"}

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username   = Column(String(50), nullable=False, unique=True)
    email      = Column(String(100), nullable=False, unique=True)
    password   = Column(String, nullable=False)
    role_id    = Column(Integer, ForeignKey("global.roles.id"), nullable=False)
    company_id = Column(UUID(as_uuid=True), ForeignKey("global.companies.id"), nullable=True)
    created_at = Column(DateTime, server_default=text("now()"))
    is_active  = Column(Boolean, default=False, nullable=False)

    role    = relationship("Role", backref="users")
    company = relationship("Company", backref="users")
