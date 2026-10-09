import re
from uuid import UUID
from sqlalchemy import inspect, text
from sqlalchemy.exc import NoInspectionAvailable
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
    _migrate_existing_tenant_schema(connection, schema_name)

def _migrate_existing_tenant_schema(connection, schema_name: str) -> None:
    try:
        inspector = inspect(connection)
    except NoInspectionAvailable:
        return

    required_columns = {
        "venta": {
            "tasa_impuesto": "NUMERIC(5, 2) NOT NULL DEFAULT 0",
            "es_exenta": "BOOLEAN NOT NULL DEFAULT FALSE",
        },
        "configuracion_tributaria": {
            "perfil_tributario": "JSON NULL",
        },
        "fiscal_document": {
            "direction": "VARCHAR(20) NOT NULL DEFAULT 'INPUT'",
        },
        "tax_component": {
            "tax_name": "VARCHAR(150) NULL",
            "retention_id": "VARCHAR(150) NULL",
            "withholding_type": "VARCHAR(50) NULL",
            "withholding_role": "VARCHAR(50) NULL",
            "applied_to": "VARCHAR(50) NULL",
            "withholding_effect": "VARCHAR(30) NULL",
        },
        "import_mapping": {
            "description": "VARCHAR(500) NULL",
            "encoding": "VARCHAR(50) NULL",
            "date_format": "VARCHAR(20) NULL",
            "decimal_separator": "VARCHAR(1) NULL",
            "thousands_separator": "VARCHAR(1) NULL",
            "header_row": "INTEGER NOT NULL DEFAULT 1",
            "data_start_row": "INTEGER NULL",
            "group_by": "JSON NULL",
            "is_active": "BOOLEAN NOT NULL DEFAULT TRUE",
        },
    }

    for table_name, columns in required_columns.items():
        existing = {
            column["name"]

            for column in inspector.get_columns(table_name, schema=schema_name)
        }

        for column_name, ddl in columns.items():
            if column_name not in existing:
                connection.execute(
                    text(
                        f'ALTER TABLE "{schema_name}"."{table_name}" '
                        f'ADD COLUMN "{column_name}" {ddl}'
                    )
                )

    config = f'"{schema_name}"."configuracion_tributaria"'
    connection.execute(
        text(
            f"""
            DELETE FROM {config}
            WHERE id NOT IN (
                SELECT id
                FROM {config}
                ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST, id
                LIMIT 1
            )
            """
        )
    )