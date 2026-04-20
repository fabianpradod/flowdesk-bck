from sqlalchemy import Table, Column, Integer, ForeignKey
from app.core.database import Base

role_permissions = Table(
    "role_permissions", 
    Base.metadata,
    Column("role_id", Integer, ForeignKey("global.roles.id")),
    Column("permission_id", Integer, ForeignKey("global.permissions.id")),
    schema = "global"
)