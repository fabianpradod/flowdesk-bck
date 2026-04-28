import re
from uuid import UUID

from sqlalchemy import text

from app.models.tenant.registry import build_tenant_metadata, get_tenant_table_names


SCHEMA_NAME_RE = re.compile(r"^tenant_[a-f0-9]{32}$")


def generate_schema_name(company_id: UUID) -> str:
    return f"tenant_{company_id.hex}"


def validate_schema_name(schema_name: str) -> None:
    if not SCHEMA_NAME_RE.fullmatch(schema_name):
        raise ValueError("Invalid tenant schema name")


def bootstrap_tenant_schema(connection, schema_name: str) -> None:
    validate_schema_name(schema_name)
    connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))
    metadata = build_tenant_metadata(schema_name)
    tenant_tables = [
        metadata.tables[f"{schema_name}.{table_name}"]
        for table_name in get_tenant_table_names()
    ]
    metadata.create_all(bind=connection, tables=tenant_tables)
