import uuid

from sqlalchemy import Column, Date, DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import UUID

from app.models.tenant.base import Base, TENANT_SCHEMA


class Tarea(Base):
    __tablename__ = "tarea"
    __table_args__ = {"schema": TENANT_SCHEMA}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    usuario_id = Column(UUID(as_uuid=True), ForeignKey("global.users.id"), nullable=False)
    titulo = Column(String(100), nullable=False)
    descripcion = Column(Text, nullable=True)
    fecha_limite = Column(DateTime, nullable=True)
    estado = Column(String(20), nullable=False, server_default=text("'pendiente'"))
    prioridad = Column(String(20), nullable=False, server_default=text("'media'"))
    created_at = Column(DateTime, nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("now()"))


class Reporte(Base):
    __tablename__ = "reporte"
    __table_args__ = {"schema": TENANT_SCHEMA}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tipo = Column(String(50), nullable=False)
    periodo_inicio = Column(Date, nullable=True)
    periodo_fin = Column(Date, nullable=True)
    formato = Column(String(20), nullable=False)
    estado = Column(String(20), nullable=False, server_default=text("'generado'"))
    generado_por_usuario_id = Column(UUID(as_uuid=True), ForeignKey("global.users.id"), nullable=True)
    fecha_generacion = Column(DateTime, nullable=False, server_default=text("now()"))
    ruta_archivo = Column(String(255), nullable=True)
