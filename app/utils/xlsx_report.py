from decimal import Decimal
from io import BytesIO
from typing import Any
from openpyxl import Workbook
from openpyxl.styles import Font
from app.schemas.reports import ReportDataset, ReportSheet, ReportWorkbook

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

def render_xlsx(report: ReportDataset | ReportWorkbook) -> bytes:
    """Render a report using typed Excel cells and safe text values."""
    workbook = Workbook()
    workbook.remove(workbook.active)
    sheets = _sheets(report)

    for sheet in sheets:
        worksheet = workbook.create_sheet(title=sheet.name)
        worksheet.append(sheet.columns)

        for cell in worksheet[1]:
            cell.font = Font(bold=True)

        worksheet.freeze_panes = "A2"
        
        for row in sheet.rows:
            worksheet.append([_safe_value(value) for value in row])

        _set_widths(worksheet)

    output = BytesIO()
    workbook.save(output)

    return output.getvalue()

def _sheets(report: ReportDataset | ReportWorkbook) -> list[ReportSheet]:
    if isinstance(report, ReportWorkbook):
        return report.sheets
    
    return [ReportSheet(name=_sheet_name(report.title), columns=report.columns, rows=report.rows)]

def _sheet_name(title: str) -> str:
    invalid = set("[]:*?/\\")
    name = "".join("_" if char in invalid else char for char in title).strip()

    return (name or "Reporte")[:31]

def _safe_value(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    
    if isinstance(value, Decimal):
        return float(value)
    
    return value

def _set_widths(worksheet) -> None:
    for column in worksheet.columns:
        width = max(len(str(cell.value or "")) for cell in column) + 2
        worksheet.column_dimensions[column[0].column_letter].width = min(width, 45)