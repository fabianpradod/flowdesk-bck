import uuid

from sqlalchemy import Column, String, Integer, DateTime, text
from sqlalchemy.orm import relationship

from app.models.role_permissions import role_permissions
from app.core.database import Base

class Role(Base):
    __tablename__  = "roles"
    __table_args__ = {"schema": "global"}

    id          = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(String(50), nullable=False, unique=True)
    description = Column(String(255), nullable=True)
    created_at  = Column(DateTime, server_default=text("now()"))

permissions = relationship(
    "Permission",
    secondary = role_permissions,
    backref = "roles"
)