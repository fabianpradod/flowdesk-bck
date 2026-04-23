import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID

from app.models.tenant.base import Base, TENANT_SCHEMA


class Proveedor(Base):
    __tablename__ = "proveedor"
    __table_args__ = {"schema": TENANT_SCHEMA}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre = Column(String(100), nullable=False)
    telefono = Column(String(20), nullable=True)
    correo = Column(String(150), nullable=True)
    direccion = Column(String(200), nullable=True)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime, nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("now()"))


class Producto(Base):
    __tablename__ = "producto"
    __table_args__ = (
        CheckConstraint("stock_actual >= 0", name="ck_producto_stock_actual_nonnegative"),
        CheckConstraint("stock_minimo >= 0", name="ck_producto_stock_minimo_nonnegative"),
        {"schema": TENANT_SCHEMA},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    proveedor_id = Column(UUID(as_uuid=True), ForeignKey(f"{TENANT_SCHEMA}.proveedor.id"), nullable=True)
    sku = Column(String(50), nullable=False, unique=True)
    nombre = Column(String(100), nullable=False)
    descripcion = Column(Text, nullable=True)
    precio_venta = Column(Numeric(10, 2), nullable=False, server_default=text("0"))
    stock_actual = Column(Numeric(12, 2), nullable=False, server_default=text("0"))
    stock_minimo = Column(Numeric(12, 2), nullable=False, server_default=text("0"))
    unidad_medida = Column(String(20), nullable=False, server_default=text("'unidad'"))
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime, nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("now()"))


class MovimientoInventario(Base):
    __tablename__ = "movimiento_inventario"
    __table_args__ = (
        CheckConstraint("cantidad > 0", name="ck_movimiento_inventario_cantidad_positive"),
        {"schema": TENANT_SCHEMA},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    producto_id = Column(UUID(as_uuid=True), ForeignKey(f"{TENANT_SCHEMA}.producto.id"), nullable=False)
    usuario_id = Column(UUID(as_uuid=True), ForeignKey("global.users.id"), nullable=True)
    tipo_movimiento = Column(String(30), nullable=False)
    fecha = Column(DateTime, nullable=False, server_default=text("now()"))
    cantidad = Column(Numeric(12, 2), nullable=False)
    stock_anterior = Column(Numeric(12, 2), nullable=False)
    stock_resultante = Column(Numeric(12, 2), nullable=False)
    motivo = Column(String(200), nullable=True)
    referencia_tipo = Column(String(30), nullable=True)
    referencia_id = Column(UUID(as_uuid=True), nullable=True)


class Alerta(Base):
    __tablename__ = "alerta"
    __table_args__ = {"schema": TENANT_SCHEMA}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    producto_id = Column(UUID(as_uuid=True), ForeignKey(f"{TENANT_SCHEMA}.producto.id"), nullable=False)
    tipo = Column(String(50), nullable=False)
    mensaje = Column(String(255), nullable=False)
    fecha = Column(DateTime, nullable=False, server_default=text("now()"))
    estado = Column(String(20), nullable=False, server_default=text("'pendiente'"))
    resuelta_en = Column(DateTime, nullable=True)
