from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


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

    @model_validator(mode="after")
    def require_update_field(self):
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self


class ClientStatusUpdate(BaseModel):
    is_active: bool


class ClientResponse(ClientBase):
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
    impuesto: Decimal = Field(default=Decimal("0"), ge=0, max_digits=10, decimal_places=2)

    @model_validator(mode="after")
    def reject_duplicate_products(self):
        product_ids = [item.producto_id for item in self.items]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("Each product may appear only once per sale")
        return self


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
    total: Decimal
    estado: str
    items: list[SaleItemResponse]
