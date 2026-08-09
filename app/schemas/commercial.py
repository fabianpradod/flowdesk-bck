from datetime import datetime
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


class ClientStatusUpdate(BaseModel):
    is_active: bool


class ClientResponse(ClientBase):
    id: UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
