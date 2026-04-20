from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


MovementType = Literal[
    "entrada_compra",
    "entrada_manual",
    "ajuste_positivo",
    "devolucion_cliente",
    "salida_venta",
    "salida_manual",
    "ajuste_negativo",
    "devolucion_proveedor",
]


class SupplierCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    telefono: str | None = Field(default=None, max_length=20)
    correo: str | None = Field(default=None, max_length=150)
    direccion: str | None = Field(default=None, max_length=200)


class SupplierResponse(BaseModel):
    id: UUID
    nombre: str
    telefono: str | None
    correo: str | None
    direccion: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=50)
    nombre: str = Field(min_length=1, max_length=100)
    descripcion: str | None = None
    precio_venta: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)
    stock_minimo: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)
    unidad_medida: str = Field(default="unidad", min_length=1, max_length=20)
    proveedor_id: UUID | None = None


class ProductResponse(BaseModel):
    id: UUID
    proveedor_id: UUID | None
    sku: str
    nombre: str
    descripcion: str | None
    precio_venta: Decimal
    stock_actual: Decimal
    stock_minimo: Decimal
    unidad_medida: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InventoryMovementCreate(BaseModel):
    producto_id: UUID
    tipo_movimiento: MovementType
    cantidad: Decimal = Field(gt=0, decimal_places=2)
    motivo: str | None = Field(default=None, max_length=200)
    referencia_tipo: str | None = Field(default=None, max_length=30)
    referencia_id: UUID | None = None


class InventoryMovementResponse(BaseModel):
    id: UUID
    producto_id: UUID
    usuario_id: UUID | None
    tipo_movimiento: str
    fecha: datetime
    cantidad: Decimal
    stock_anterior: Decimal
    stock_resultante: Decimal
    motivo: str | None
    referencia_tipo: str | None
    referencia_id: UUID | None

    model_config = ConfigDict(from_attributes=True)


class InventoryAlertResponse(BaseModel):
    id: UUID
    producto_id: UUID
    tipo: str
    mensaje: str
    fecha: datetime
    estado: str
    resuelta_en: datetime | None

    model_config = ConfigDict(from_attributes=True)
