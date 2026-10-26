from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.schemas.base import StrippedModel


class ClientBase(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    telefono: Optional[str] = Field(default=None, max_length=20)
    correo: Optional[EmailStr] = Field(default=None, max_length=150)
    direccion: Optional[str] = Field(default=None, max_length=200)

    @field_validator("nombre", "telefono", "direccion", mode="before")
    @classmethod
    def strip_text(cls, value):
        if value is None:
            return value
        return str(value).strip()

    @field_validator("correo", mode="before")
    @classmethod
    def normalize_email(cls, value):
        if value is None:
            return value
        cleaned = str(value).strip().lower()
        return cleaned or None


class ClientCreate(ClientBase):
    pass


class ClientUpdate(BaseModel):
    nombre: Optional[str] = Field(default=None, min_length=1, max_length=100)
    telefono: Optional[str] = Field(default=None, max_length=20)
    correo: Optional[EmailStr] = Field(default=None, max_length=150)
    direccion: Optional[str] = Field(default=None, max_length=200)

    @field_validator("nombre", "telefono", "direccion", mode="before")
    @classmethod
    def strip_text(cls, value):
        if value is None:
            return value
        
        return str(value).strip()

    @field_validator("correo", mode="before")
    @classmethod
    def normalize_email(cls, value):
        if value is None:
            return value
        
        cleaned = str(value).strip().lower()
        return cleaned or None


class ClientStatusUpdate(BaseModel):
    is_active: bool


class ClientResponse(ClientBase):
    # Stored emails were validated on the way in. EmailStr here ran the validator again
    # for every client of every listing, which was most of the time of GET /clients.
    correo: Optional[str] = Field(default=None, max_length=150)
    id: UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SaleItemCreate(BaseModel):
    producto_id: UUID
    cantidad: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class SaleCreate(BaseModel):
    cliente_id: UUID | None = None
    items: list[SaleItemCreate] = Field(min_length=1, max_length=100)
    descuento: Decimal = Field(default=Decimal("0"), ge=0, max_digits=10, decimal_places=2)
    es_exenta: bool = False

    @model_validator(mode="after")
    def reject_duplicate_products(self):
        product_ids = [item.producto_id for item in self.items]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("Each product may appear only once per sale")
        return self


class SaleVoid(StrippedModel):
    motivo: str = Field(min_length=1, max_length=200)


class SaleItemResponse(BaseModel):
    id: UUID
    producto_id: UUID
    cantidad: Decimal
    precio_unitario: Decimal
    subtotal: Decimal


class SaleResponse(BaseModel):
    id: UUID
    usuario_id: UUID
    cliente_id: UUID | None
    consumidor_final: bool
    cliente_nombre: str | None = None
    fecha: datetime
    subtotal: Decimal
    descuento: Decimal
    impuesto: Decimal
    tasa_impuesto: Decimal
    es_exenta: bool
    total: Decimal
    estado: str
    motivo_anulacion: str | None = None
    anulada_por: UUID | None = None
    anulada_en: datetime | None = None
    items: list[SaleItemResponse]

class TaxConfigurationUpdate(BaseModel):
    tasa_impuesto: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)

class TaxConfigurationResponse(BaseModel):
    tasa_impuesto: Decimal
