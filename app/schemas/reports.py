from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


ReportFormat = Literal["csv", "pdf"]
ReportType = Literal["inventario", "movimientos", "alertas"]

REPORT_MEDIA_TYPES: dict[str, str] = {
    "csv": "text/csv; charset=utf-8",
    "pdf": "application/pdf",
}


class ReportHistoryRow(BaseModel):
    id: UUID
    tipo: str
    formato: str
    periodo_inicio: date | None
    periodo_fin: date | None
    estado: str
    generado_por_usuario_id: UUID | None
    fecha_generacion: datetime

    model_config = ConfigDict(from_attributes=True)
