from sqlalchemy import Column, MetaData, Table
from sqlalchemy.dialects.postgresql import UUID

from app.models.tenant.base import Base, TENANT_SCHEMA
from app.models.tenant.commercial import Cliente, DetalleVenta, Venta
from app.models.tenant.inventory import Alerta, MovimientoInventario, Producto, Proveedor
from app.models.tenant.operations import Reporte, Tarea


TENANT_MODELS = (
    Proveedor,
    Cliente,
    Producto,
    Venta,
    DetalleVenta,
    Tarea,
    Reporte,
    MovimientoInventario,
    Alerta,
)


def get_tenant_table_names() -> tuple[str, ...]:
    return tuple(model.__tablename__ for model in TENANT_MODELS)


def build_tenant_metadata(schema_name: str) -> MetaData:
    metadata = MetaData()
    _attach_global_table_stubs(metadata)
    for model in TENANT_MODELS:
        model.__table__.to_metadata(
            metadata,
            schema=schema_name,
            referred_schema_fn=_translate_referred_schema(schema_name),
        )
    return metadata


def _translate_referred_schema(schema_name: str):
    def translate(_table, _to_schema, _constraint, referred_schema):
        if referred_schema == TENANT_SCHEMA:
            return schema_name
        return referred_schema

    return translate


def _attach_global_table_stubs(metadata: MetaData) -> None:
    # This stub resolves cross-schema FKs without owning the global users table.
    Table(
        "users",
        metadata,
        Column("id", UUID(as_uuid=True), primary_key=True),
        schema="global",
        extend_existing=True,
    )
