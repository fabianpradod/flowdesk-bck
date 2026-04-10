import uuid

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import Column, String, Boolean, DateTime, text

from app.core.database import Base

class Company(Base):
    __tablename__  = "companies"
    __table_args__ = {"schema": "global"}

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name        = Column(String(100), nullable=False)
    schema_name = Column(String(50), nullable=False, unique=True)
    is_active   = Column(Boolean, default=True, nullable=False)
    created_at  = Column(DateTime, server_default=text("now()"))