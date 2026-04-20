import re
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID


SCHEMA_NAME_RE = re.compile(r"^tenant_[a-f0-9]{32}$")


def generate_schema_name(company_id: UUID) -> str:
    return f"tenant_{company_id.hex}"


def validate_schema_name(schema_name: str) -> None:
    if not SCHEMA_NAME_RE.fullmatch(schema_name):
        raise ValueError("Invalid tenant schema name")


def build_tenant_metadata(schema_name: str) -> MetaData:
    validate_schema_name(schema_name)
    metadata = MetaData()

    Table(
        "proveedor",
        metadata,
        Column("id", PGUUID(as_uuid=True), primary_key=True),
        Column("nombre", String(100), nullable=False),
        Column("telefono", String(20)),
        Column("correo", String(150)),
        Column("direccion", String(200)),
        Column("is_active", Boolean, nullable=False, server_default=text("true")),
        Column("created_at", DateTime, nullable=False, server_default=text("now()")),
        Column("updated_at", DateTime, nullable=False, server_default=text("now()")),
        schema=schema_name,
    )

    Table(
        "cliente",
        metadata,
        Column("id", PGUUID(as_uuid=True), primary_key=True),
        Column("nombre", String(100), nullable=False),
        Column("telefono", String(20)),
        Column("correo", String(150)),
        Column("direccion", String(200)),
        Column("is_active", Boolean, nullable=False, server_default=text("true")),
        Column("created_at", DateTime, nullable=False, server_default=text("now()")),
        Column("updated_at", DateTime, nullable=False, server_default=text("now()")),
        schema=schema_name,
    )

    Table(
        "producto",
        metadata,
        Column("id", PGUUID(as_uuid=True), primary_key=True),
        Column("proveedor_id", PGUUID(as_uuid=True), ForeignKey(f"{schema_name}.proveedor.id")),
        Column("sku", String(50), nullable=False, unique=True),
        Column("nombre", String(100), nullable=False),
        Column("descripcion", Text),
        Column("precio_venta", Numeric(10, 2), nullable=False, server_default=text("0")),
        Column("stock_actual", Numeric(12, 2), nullable=False, server_default=text("0")),
        Column("stock_minimo", Numeric(12, 2), nullable=False, server_default=text("0")),
        Column("unidad_medida", String(20), nullable=False, server_default=text("'unidad'")),
        Column("is_active", Boolean, nullable=False, server_default=text("true")),
        Column("created_at", DateTime, nullable=False, server_default=text("now()")),
        Column("updated_at", DateTime, nullable=False, server_default=text("now()")),
        CheckConstraint("stock_actual >= 0", name="ck_producto_stock_actual_nonnegative"),
        CheckConstraint("stock_minimo >= 0", name="ck_producto_stock_minimo_nonnegative"),
        schema=schema_name,
    )

    Table(
        "venta",
        metadata,
        Column("id", PGUUID(as_uuid=True), primary_key=True),
        Column("usuario_id", PGUUID(as_uuid=True), ForeignKey("global.users.id"), nullable=False),
        Column("cliente_id", PGUUID(as_uuid=True), ForeignKey(f"{schema_name}.cliente.id")),
        Column("fecha", DateTime, nullable=False, server_default=text("now()")),
        Column("subtotal", Numeric(10, 2), nullable=False, server_default=text("0")),
        Column("descuento", Numeric(10, 2), nullable=False, server_default=text("0")),
        Column("impuesto", Numeric(10, 2), nullable=False, server_default=text("0")),
        Column("total", Numeric(10, 2), nullable=False, server_default=text("0")),
        Column("estado", String(20), nullable=False, server_default=text("'borrador'")),
        Column("created_at", DateTime, nullable=False, server_default=text("now()")),
        Column("updated_at", DateTime, nullable=False, server_default=text("now()")),
        schema=schema_name,
    )

    Table(
        "detalle_venta",
        metadata,
        Column("id", PGUUID(as_uuid=True), primary_key=True),
        Column("venta_id", PGUUID(as_uuid=True), ForeignKey(f"{schema_name}.venta.id"), nullable=False),
        Column("producto_id", PGUUID(as_uuid=True), ForeignKey(f"{schema_name}.producto.id"), nullable=False),
        Column("cantidad", Numeric(12, 2), nullable=False),
        Column("precio_unitario", Numeric(10, 2), nullable=False),
        Column("subtotal", Numeric(10, 2), nullable=False),
        CheckConstraint("cantidad > 0", name="ck_detalle_venta_cantidad_positive"),
        schema=schema_name,
    )

    Table(
        "tarea",
        metadata,
        Column("id", PGUUID(as_uuid=True), primary_key=True),
        Column("usuario_id", PGUUID(as_uuid=True), ForeignKey("global.users.id"), nullable=False),
        Column("titulo", String(100), nullable=False),
        Column("descripcion", Text),
        Column("fecha_limite", DateTime),
        Column("estado", String(20), nullable=False, server_default=text("'pendiente'")),
        Column("prioridad", String(20), nullable=False, server_default=text("'media'")),
        Column("created_at", DateTime, nullable=False, server_default=text("now()")),
        Column("updated_at", DateTime, nullable=False, server_default=text("now()")),
        schema=schema_name,
    )

    Table(
        "reporte",
        metadata,
        Column("id", PGUUID(as_uuid=True), primary_key=True),
        Column("tipo", String(50), nullable=False),
        Column("periodo_inicio", Date),
        Column("periodo_fin", Date),
        Column("formato", String(20), nullable=False),
        Column("estado", String(20), nullable=False, server_default=text("'generado'")),
        Column("generado_por_usuario_id", PGUUID(as_uuid=True), ForeignKey("global.users.id")),
        Column("fecha_generacion", DateTime, nullable=False, server_default=text("now()")),
        Column("ruta_archivo", String(255)),
        schema=schema_name,
    )

    Table(
        "movimiento_inventario",
        metadata,
        Column("id", PGUUID(as_uuid=True), primary_key=True),
        Column("producto_id", PGUUID(as_uuid=True), ForeignKey(f"{schema_name}.producto.id"), nullable=False),
        Column("usuario_id", PGUUID(as_uuid=True), ForeignKey("global.users.id")),
        Column("tipo_movimiento", String(30), nullable=False),
        Column("fecha", DateTime, nullable=False, server_default=text("now()")),
        Column("cantidad", Numeric(12, 2), nullable=False),
        Column("stock_anterior", Numeric(12, 2), nullable=False),
        Column("stock_resultante", Numeric(12, 2), nullable=False),
        Column("motivo", String(200)),
        Column("referencia_tipo", String(30)),
        Column("referencia_id", PGUUID(as_uuid=True)),
        CheckConstraint("cantidad > 0", name="ck_movimiento_inventario_cantidad_positive"),
        schema=schema_name,
    )

    Table(
        "alerta",
        metadata,
        Column("id", PGUUID(as_uuid=True), primary_key=True),
        Column("producto_id", PGUUID(as_uuid=True), ForeignKey(f"{schema_name}.producto.id"), nullable=False),
        Column("tipo", String(50), nullable=False),
        Column("mensaje", String(255), nullable=False),
        Column("fecha", DateTime, nullable=False, server_default=text("now()")),
        Column("estado", String(20), nullable=False, server_default=text("'pendiente'")),
        Column("resuelta_en", DateTime),
        schema=schema_name,
    )

    return metadata


def _attach_global_table_stubs(metadata: MetaData) -> None:
    # These stubs let SQLAlchemy resolve cross-schema foreign keys during
    # tenant DDL generation without attempting to own or recreate global tables.
    Table(
        "users",
        metadata,
        Column("id", PGUUID(as_uuid=True), primary_key=True),
        schema="global",
        extend_existing=True,
    )


def bootstrap_tenant_schema(connection, schema_name: str) -> None:
    validate_schema_name(schema_name)
    connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))
    metadata = build_tenant_metadata(schema_name)
    _attach_global_table_stubs(metadata)
    tenant_tables = [table for table in metadata.tables.values() if table.schema == schema_name]
    metadata.create_all(bind=connection, tables=tenant_tables)
