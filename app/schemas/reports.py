from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


ReportFormat = Literal["csv", "pdf"]
ReportType = Literal["inventario", "movimientos", "alertas", "tributario"]
TaxReportRegime = Literal["SMALL_TAXPAYER", "GENERAL_VAT"]

REPORT_MEDIA_TYPES: dict[str, str] = {
    "csv": "text/csv; charset=utf-8",
    "pdf": "application/pdf",
}
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@dataclass
class ReportDataset:
    """The seam between data and format: builders produce it, renderers consume it."""

    title: str
    columns: list[str]
    rows: list[list[Any]]
    metadata: dict

@dataclass
class ReportSheet:
    name: str
    columns: list[str]
    rows: list[list[Any]]

@dataclass
class ReportWorkbook:
    title: str
    sheets: list[ReportSheet]
    metadata: dict


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
