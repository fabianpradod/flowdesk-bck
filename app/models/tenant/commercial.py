import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID

from app.models.tenant.base import Base, TENANT_SCHEMA


class Cliente(Base):
    __tablename__ = "cliente"
    __table_args__ = {"schema": TENANT_SCHEMA}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre = Column(String(100), nullable=False)
    telefono = Column(String(20), nullable=True)
    correo = Column(String(150), nullable=True)
    direccion = Column(String(200), nullable=True)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime, nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("now()"))


class Venta(Base):
    __tablename__ = "venta"
    __table_args__ = {"schema": TENANT_SCHEMA}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    usuario_id = Column(UUID(as_uuid=True), ForeignKey("global.users.id"), nullable=False)
    cliente_id = Column(UUID(as_uuid=True), ForeignKey(f"{TENANT_SCHEMA}.cliente.id"), nullable=True)
    fecha = Column(DateTime, nullable=False, server_default=text("now()"))
    subtotal = Column(Numeric(10, 2), nullable=False, server_default=text("0"))
    descuento = Column(Numeric(10, 2), nullable=False, server_default=text("0"))
    impuesto = Column(Numeric(10, 2), nullable=False, server_default=text("0"))
    total = Column(Numeric(10, 2), nullable=False, server_default=text("0"))
    estado = Column(String(20), nullable=False, server_default=text("'borrador'"))
    created_at = Column(DateTime, nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("now()"))


class DetalleVenta(Base):
    __tablename__ = "detalle_venta"
    __table_args__ = (
        CheckConstraint("cantidad > 0", name="ck_detalle_venta_cantidad_positive"),
        {"schema": TENANT_SCHEMA},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    venta_id = Column(UUID(as_uuid=True), ForeignKey(f"{TENANT_SCHEMA}.venta.id"), nullable=False)
    producto_id = Column(UUID(as_uuid=True), ForeignKey(f"{TENANT_SCHEMA}.producto.id"), nullable=False)
    cantidad = Column(Numeric(12, 2), nullable=False)
    precio_unitario = Column(Numeric(10, 2), nullable=False)
    subtotal = Column(Numeric(10, 2), nullable=False)
