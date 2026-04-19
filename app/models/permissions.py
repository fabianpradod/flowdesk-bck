from sqlalchemy import Column, Integer, String
from app.core.database import Base

class Permission(Base):
    _tablename_ = "permissions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)