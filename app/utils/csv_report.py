import csv
from decimal import Decimal, InvalidOperation
from io import StringIO

from app.schemas.reports import ReportDataset

# A cell opening with one of these is read as a formula by Excel and LibreOffice.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
UTF8_BOM = "﻿"


def render_csv(dataset: ReportDataset) -> bytes:
    """Renders a dataset as CSV. Includes a BOM so Excel reads the accents correctly."""
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow([escape_formula(column) for column in dataset.columns])
    for row in dataset.rows:
        writer.writerow([escape_formula(cell) for cell in row])
    return (UTF8_BOM + buffer.getvalue()).encode("utf-8")


def escape_formula(value: str) -> str:
    """Neutralizes spreadsheet formula injection on export, mirroring the guard on import."""
    text = "" if value is None else str(value)
    if text.startswith(FORMULA_PREFIXES) and not _is_number(text):
        return f"'{text}"
    return text


def _is_number(text: str) -> bool:
    # A plain number can't be a formula, so a negative amount stays numeric in the sheet.
    try:
        return Decimal(text).is_finite()
    except InvalidOperation:
        return False
