from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


TaskStatus = Literal["pendiente", "en_progreso", "completada", "cancelada"]
TaskPriority = Literal["baja", "media", "alta", "urgente"]


class TaskCreate(BaseModel):
    titulo: str = Field(min_length=1, max_length=100)
    descripcion: str | None = None
    fecha_limite: datetime | None = None
    prioridad: TaskPriority = "media"

    @field_validator("titulo", mode="before")
    @classmethod
    def strip_title(cls, value):
        return str(value).strip() if value is not None else value

    @field_validator("descripcion", mode="before")
    @classmethod
    def normalize_description(cls, value):
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None


class TaskUpdate(BaseModel):
    titulo: str | None = Field(default=None, min_length=1, max_length=100)
    descripcion: str | None = None
    fecha_limite: datetime | None = None
    prioridad: TaskPriority | None = None

    @field_validator("titulo", mode="before")
    @classmethod
    def strip_title(cls, value):
        return str(value).strip() if value is not None else value

    @field_validator("descripcion", mode="before")
    @classmethod
    def normalize_description(cls, value):
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @model_validator(mode="after")
    def require_update_field(self):
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        if "titulo" in self.model_fields_set and self.titulo is None:
            raise ValueError("Title cannot be null")
        if "prioridad" in self.model_fields_set and self.prioridad is None:
            raise ValueError("Priority cannot be null")
        return self


class TaskStatusUpdate(BaseModel):
    estado: TaskStatus


class TaskResponse(BaseModel):
    id: UUID
    usuario_id: UUID
    titulo: str
    descripcion: str | None
    fecha_limite: datetime | None
    estado: TaskStatus
    prioridad: TaskPriority
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
