from sqlalchemy import Column, Integer, String
from app.core.database import Base

class Permission(Base):
    __tablename__ = "permissions"
    __table_args__ = {"schema": "global"}

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)