import uuid

from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import Column, String, DateTime, ForeignKey, text

from app.core.database import Base

class User(Base):
    __tablename__  = "users"
    __table_args__ = {"schema": "global"}

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username   = Column(String(50), nullable=False, unique=True)
    email      = Column(String(100), nullable=False, unique=True)
    password   = Column(String, nullable=False)
    role       = Column(String(20), nullable=False, default="employee")
    company_id = Column(UUID(as_uuid=True), ForeignKey("global.companies.id"), nullable=False)
    created_at = Column(DateTime, server_default=text("now()"))

    company = relationship("Company", backref="users")