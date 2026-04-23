from sqlalchemy import Column, Table
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base


TENANT_SCHEMA = "tenant"
Base = declarative_base()

# Stub used only for resolving cross-schema foreign keys from tenant tables.
Table(
    "users",
    Base.metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    schema="global",
    extend_existing=True,
)
