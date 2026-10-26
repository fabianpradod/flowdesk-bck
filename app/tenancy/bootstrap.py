import re
from uuid import UUID
from sqlalchemy import inspect, text
from sqlalchemy.exc import NoInspectionAvailable
from sqlalchemy.schema import CreateIndex
from app.models.tenant.registry import build_tenant_metadata, get_tenant_table_names
from app.utils.logger import logger


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
    _ensure_partial_unique_indexes(connection, schema_name, tenant_tables)


def _ensure_partial_unique_indexes(connection, schema_name: str, tables) -> None:
    """Give tenants whose tables predate a partial unique index the declared version.

    create_all builds indexes only together with a new table, so an older tenant has
    no index, or the one declared before the current condition, and the database
    stops guarding the rule. A tenant that already holds duplicates is skipped with
    a warning instead of failing the startup.
    """
    if connection.dialect.name != "postgresql":
        return
    for table in tables:
        for index in table.indexes:
            where = index.dialect_options["postgresql"]["where"]
            if not index.unique or where is None:
                continue
            definition = connection.execute(
                text("SELECT indexdef FROM pg_indexes WHERE schemaname = :schema AND indexname = :name"),
                {"schema": schema_name, "name": index.name},
            ).scalar()
            if definition is not None and _same_condition(definition, str(where)):
                continue
            expressions = ", ".join(str(expression) for expression in index.expressions)
            duplicate = connection.execute(
                text(
                    f'SELECT 1 FROM "{schema_name}"."{table.name}" WHERE {where} '
                    f"GROUP BY {expressions} HAVING count(*) > 1 LIMIT 1"
                )
            ).first()
            if duplicate is not None:
                logger.warning(
                    "Tenant %s has duplicate rows for %s; the unique index was not created",
                    schema_name,
                    index.name,
                )
                continue
            if definition is not None:
                connection.execute(text(f'DROP INDEX "{schema_name}"."{index.name}"'))
            connection.execute(CreateIndex(index))


def _same_condition(definition: str, where: str) -> bool:
    # Postgres stores the condition with its own parentheses and spacing.
    if " WHERE " not in definition:
        return False
    normalize = lambda value: re.sub(r"[\s()]", "", value).lower()
    return normalize(definition.split(" WHERE ", 1)[1]) == normalize(where)

def _migrate_existing_tenant_schema(connection, schema_name: str) -> None:
    try:
        inspector = inspect(connection)
    except NoInspectionAvailable:
        return

    required_columns = {
        "venta": {
            "tasa_impuesto": "NUMERIC(5, 2) NOT NULL DEFAULT 0",
            "es_exenta": "BOOLEAN NOT NULL DEFAULT FALSE",
            "motivo_anulacion": "VARCHAR(200) NULL",
            "anulada_por": 'UUID NULL REFERENCES "global".users (id)',
            "anulada_en": "TIMESTAMP NULL",
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