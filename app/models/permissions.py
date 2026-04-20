from sqlalchemy import Column, Integer, String
from app.core.database import Base

class Permission(Base):
    _tablename_ = "permissions"
    _table_args_ = {"schema": "global"}

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)