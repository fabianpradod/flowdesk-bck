import uuid

from sqlalchemy import Column, String, Integer, DateTime, text

from app.core.database import Base

class Role(Base):
    __tablename__  = "roles"
    __table_args__ = {"schema": "global"}

    id          = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(String(50), nullable=False, unique=True)
    description = Column(String(255), nullable=True)
    created_at  = Column(DateTime, server_default=text("now()"))