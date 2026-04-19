from sqlalchemy import Column, Integer, Table, ForeignKey
from app.core.database import Base

user_permissions = Table(
    "user_permissions",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id")),
    Column("permission_id", Integer, ForeignKey("permission.id"))
)