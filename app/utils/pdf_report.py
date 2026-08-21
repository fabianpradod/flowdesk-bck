from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer

from app.services.reports import ReportDataset

PAGE_SIZE = landscape(A4)
PAGE_MARGIN = 15 * mm
HEADER_BACKGROUND = colors.HexColor("#1f3a5f")
HEADER_TEXT = colors.white
ZEBRA_BACKGROUND = colors.HexColor("#f2f5f9")
GRID_COLOR = colors.HexColor("#c9d2dd")


def render_pdf(dataset: ReportDataset) -> bytes:
    """Renders a dataset as a paginated PDF with a repeating table header."""
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=PAGE_SIZE,
        leftMargin=PAGE_MARGIN,
        rightMargin=PAGE_MARGIN,
        topMargin=PAGE_MARGIN,
        bottomMargin=PAGE_MARGIN,
        title=dataset.title,
        author="Flowdesk",
    )
    document.build(_build_story(dataset), onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return buffer.getvalue()


def _build_story(dataset: ReportDataset) -> list:
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("ReportTitle", parent=styles["Title"], fontSize=16, spaceAfter=4)
    meta_style = ParagraphStyle("ReportMeta", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#5a6572"))

    story = [Paragraph(dataset.title, title_style)]
    for line in _metadata_lines(dataset.metadata):
        story.append(Paragraph(line, meta_style))
    story.append(Spacer(1, 6 * mm))

    if not dataset.rows:
        story.append(Paragraph("No hay datos para los filtros seleccionados.", styles["Normal"]))
        return story

    story.append(_build_table(dataset))
    return story


def _metadata_lines(metadata: dict) -> list[str]:
    lines = []
    empresa = metadata.get("empresa")
    generado_por = metadata.get("generado_por")
    generated_at = metadata.get("fecha_generacion")
    if empresa:
        lines.append(f"<b>Empresa:</b> {_escape(empresa)}")
    if generado_por:
        lines.append(f"<b>Generado por:</b> {_escape(generado_por)}")
    if generated_at is not None:
        lines.append(f"<b>Fecha de generación:</b> {generated_at.strftime('%Y-%m-%d %H:%M')} UTC")
    if metadata.get("filtros"):
        lines.append(f"<b>Filtros:</b> {_escape(metadata['filtros'])}")
    return lines


def _build_table(dataset: ReportDataset) -> LongTable:
    cell_style = ParagraphStyle("ReportCell", fontName="Helvetica", fontSize=7.5, leading=9.5)
    header_style = ParagraphStyle(
        "ReportHeaderCell", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=HEADER_TEXT
    )

    data = [[Paragraph(_escape(column), header_style) for column in dataset.columns]]
    data.extend([Paragraph(_escape(cell), cell_style) for cell in row] for row in dataset.rows)

    available_width = PAGE_SIZE[0] - (2 * PAGE_MARGIN)
    column_width = available_width / len(dataset.columns)

    table = LongTable(data, colWidths=[column_width] * len(dataset.columns), repeatRows=1)
    table.setStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), HEADER_BACKGROUND),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.4, GRID_COLOR),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA_BACKGROUND]),
        ]
    )
    return table


def _draw_footer(canvas, document) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#5a6572"))
    canvas.drawRightString(
        PAGE_SIZE[0] - PAGE_MARGIN,
        PAGE_MARGIN * 0.6,
        f"Página {document.page}",
    )
    canvas.restoreState()


def _escape(value) -> str:
    """Paragraph parses its text as markup, so raw data has to be neutralized first."""
    text = "" if value is None else str(value)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
