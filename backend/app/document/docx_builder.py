"""Builds a .docx file from a validated ReportSpecification.

Purely data-driven: reads only the validated ReportSpecification. No LLM
output is interpreted here beyond the already-validated structured fields.

Visual style (colors, logo, header/footer, table treatment) is matched to
the client's own recurring "Informe de Gestión CSOC" Word template -- see
docs/style-notes if present, or the original file the client shared.
Deliberately NOT replicated: the cover's curved banner graphic and stock
photography (fragile/out of scope for python-docx, and not ours to source),
and the pervasive cyan highlight on every paragraph in their file -- that
one is applied only to each section's summary paragraph here, since across
their whole document it's used consistently as "highlight this section's
opening sentence," not as a blanket style.
"""
import io
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from app.schemas.report_spec import (
    ReportSpecification,
    Section,
    SimpleTable,
    Subsection,
)

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
LOGO_PATH = ASSETS_DIR / "invotecsa_logo.png"

DARK_GREEN = RGBColor(0x00, 0x53, 0x2A)
LIGHT_GREEN = "E2EFD9"
GRAY_TOTAL = "D9D9D9"
GRAY_BAND = "E8E8E8"
MUTED = RGBColor(0x5B, 0x66, 0x77)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

RISK_ROW_FILL = {
    "crítico": "C00000",
    "alto": "FF0000",
    "medio": "FFC000",
    "bajo": "00B050",
}
RISK_CHART_COLOR = {"Crítico": "#C00000", "Alto": "#FF0000", "Medio": "#FFC000", "Bajo": "#00B050"}


def _shade_cell(cell, hex_color: str) -> None:
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), hex_color)
    cell._tc.get_or_add_tcPr().append(shd)


def _set_cell_text(cell, text: str, *, bold: bool = False, color: RGBColor | None = None) -> None:
    cell.text = ""
    p = cell.paragraphs[0]
    run = p.add_run(text)
    run.bold = bold
    if color:
        run.font.color.rgb = color


def _style_document(document: Document) -> None:
    styles = document.styles
    styles["Normal"].font.name = "Calibri"
    styles["Normal"].font.size = Pt(11)

    h1 = styles["Heading 1"]
    h1.font.color.rgb = DARK_GREEN
    h1.font.size = Pt(16)

    h2 = styles["Heading 2"]
    h2.font.color.rgb = DARK_GREEN
    h2.font.size = Pt(13)


def _add_page_header(document: Document) -> None:
    header = document.sections[0].header
    header.is_linked_to_previous = False
    table = header.add_table(rows=1, cols=2, width=Inches(6.5))
    table.autofit = True
    left_cell, right_cell = table.rows[0].cells
    for cell in (left_cell, right_cell):
        _shade_cell(cell, GRAY_BAND)

    if LOGO_PATH.exists():
        p = left_cell.paragraphs[0]
        run = p.add_run()
        run.add_picture(str(LOGO_PATH), height=Inches(0.35))

    right_cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = right_cell.paragraphs[0].add_run("Informe de Gestión SOC")
    run.bold = True
    run.font.color.rgb = DARK_GREEN


def _add_page_footer(document: Document, spec: ReportSpecification) -> None:
    """Matches the client template's exact footer box: CÓDIGO/PÁGINA label row,
    value row (page X de Y), VERSIÓN/FECHA label row, value row, then a
    classification row spanning both columns."""
    footer = document.sections[0].footer
    footer.is_linked_to_previous = False
    dc = spec.document_control

    table = footer.add_table(rows=5, cols=2, width=Inches(3.0))
    table.alignment = WD_ALIGN_PARAGRAPH.CENTER
    table.style = "Table Grid"

    cells = table.rows[0].cells
    _set_cell_text(cells[0], "CÓDIGO", bold=True)
    _set_cell_text(cells[1], "PÁGINA", bold=True)

    cells = table.rows[1].cells
    _set_cell_text(cells[0], dc.codigo_documento)
    _add_page_of_pages_field(cells[1].paragraphs[0])

    cells = table.rows[2].cells
    _set_cell_text(cells[0], "VERSIÓN", bold=True)
    _set_cell_text(cells[1], "FECHA", bold=True)

    cells = table.rows[3].cells
    _set_cell_text(cells[0], dc.version_plantilla)
    _set_cell_text(cells[1], dc.fecha_version)

    classification_cell = table.rows[4].cells[0].merge(table.rows[4].cells[1])
    classification_cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = classification_cell.paragraphs[0].add_run(dc.clasificacion)
    run.bold = True


def _add_field(paragraph, instr_text: str) -> None:
    run = paragraph.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = instr_text
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    r = run._r
    r.append(fld_begin)
    r.append(instr)
    r.append(fld_sep)
    r.append(fld_end)


def _add_page_of_pages_field(paragraph) -> None:
    _add_field(paragraph, "PAGE")
    paragraph.add_run(" de ")
    _add_field(paragraph, "NUMPAGES")


def _add_toc(document: Document) -> None:
    paragraph = document.add_paragraph()
    run = paragraph.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = 'TOC \\o "1-2" \\h \\z \\u'
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    fld_text = OxmlElement("w:t")
    fld_text.text = "Haz clic derecho y selecciona \"Actualizar campo\" para generar la tabla de contenido."
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    r_element = run._r
    r_element.append(fld_begin)
    r_element.append(instr)
    r_element.append(fld_sep)
    r_element.append(fld_text)
    r_element.append(fld_end)


def _set_document_update_fields(document: Document) -> None:
    settings = document.settings.element
    update = OxmlElement("w:updateFields")
    update.set(qn("w:val"), "true")
    settings.append(update)


def _risk_chart_image(rows: list[list[str]]) -> io.BytesIO | None:
    """Small bar chart of alarm counts by risk level, colored to match the
    client's own red/orange/amber/green convention. Returns None if the
    table doesn't look like a risk breakdown (keeps this generic-safe)."""
    labels, values, colors = [], [], []
    for row in rows:
        label = row[0]
        color = RISK_CHART_COLOR.get(label)
        if not color:
            return None
        try:
            values.append(int(row[1]))
        except (ValueError, IndexError):
            return None
        labels.append(label)
        colors.append(color)

    fig, ax = plt.subplots(figsize=(5.5, 2.2), dpi=150)
    ax.bar(labels, values, color=colors)
    for i, v in enumerate(values):
        ax.text(i, v, str(v), ha="center", va="bottom", fontsize=9)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.set_yticks([])
    ax.tick_params(axis="x", labelsize=9)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True)
    plt.close(fig)
    buf.seek(0)
    return buf


def _add_table(document: Document, table_spec: SimpleTable) -> None:
    if not table_spec.rows:
        p = document.add_paragraph("Sin datos para el período.")
        p.runs[0].italic = True
        p.runs[0].font.color.rgb = MUTED
        return

    is_risk_table = table_spec.headers[0].strip().lower() in {"nivel de riesgo", "riesgo"}
    total_col_idx = next((i for i, h in enumerate(table_spec.headers) if h.strip().lower() == "total"), None)

    if is_risk_table:
        chart = _risk_chart_image(table_spec.rows)
        if chart:
            document.add_picture(chart, width=Inches(5.0))

    table = document.add_table(rows=1, cols=len(table_spec.headers))
    table.style = "Table Grid"
    header_cells = table.rows[0].cells
    for i, header in enumerate(table_spec.headers):
        _set_cell_text(header_cells[i], header, bold=True, color=WHITE)
        _shade_cell(header_cells[i], "00532A")

    for row in table_spec.rows:
        cells = table.add_row().cells
        row_color = RISK_ROW_FILL.get(str(row[0]).strip().lower()) if is_risk_table else None
        for i, value in enumerate(row):
            text_color = WHITE if row_color else None
            _set_cell_text(cells[i], str(value), bold=(i == 0 and is_risk_table), color=text_color)
            if row_color:
                _shade_cell(cells[i], row_color)
            elif total_col_idx is not None and i == total_col_idx:
                _shade_cell(cells[i], GRAY_TOTAL)
    document.add_paragraph()


def _add_significant_alerts(document: Document, alerts) -> None:
    for alert in alerts:
        p = document.add_paragraph()
        run = p.add_run(alert.heading)
        run.bold = True
        run.font.color.rgb = DARK_GREEN
        document.add_paragraph(alert.description)
        if alert.response:
            resp_label = document.add_paragraph()
            resp_label.add_run("Respuesta: ").bold = True
            document.add_paragraph(alert.response)


def _add_unavailable_notice(document: Document, reason: str) -> None:
    p = document.add_paragraph()
    run = p.add_run(reason or "Información no disponible con las fuentes de datos actuales.")
    run.italic = True
    run.font.color.rgb = MUTED


def _add_summary_paragraph(document: Document, text: str) -> None:
    """Cyan-highlighted, matching the one formatting rule that's consistent
    across the entire client template: highlight each section's opening
    summary sentence -- not applied elsewhere (tables, recommendations,
    alert descriptions stay plain, exactly as in their file)."""
    p = document.add_paragraph()
    run = p.add_run(text)
    run.font.highlight_color = WD_COLOR_INDEX.TURQUOISE


def _render_subsection(document: Document, sub: Subsection) -> None:
    heading = document.add_heading(level=2)
    num_run = heading.add_run(f"{sub.number} ")
    num_run.font.highlight_color = WD_COLOR_INDEX.YELLOW
    heading.add_run(sub.title)

    if not sub.available:
        _add_unavailable_notice(document, sub.unavailable_reason)
        return
    if sub.summary:
        _add_summary_paragraph(document, sub.summary)
    for line in sub.body:
        document.add_paragraph(line, style="List Bullet")
    if sub.table:
        _add_table(document, sub.table)
    if sub.significant_alerts:
        _add_significant_alerts(document, sub.significant_alerts)


def _render_section(document: Document, section: Section) -> None:
    heading = document.add_heading(level=1)
    num_run = heading.add_run(f"{section.number}. ")
    num_run.font.highlight_color = WD_COLOR_INDEX.TURQUOISE
    heading.add_run(section.title)

    if not section.available:
        _add_unavailable_notice(document, section.unavailable_reason)
        return
    if section.summary:
        _add_summary_paragraph(document, section.summary)
    for line in section.body:
        document.add_paragraph(line, style="List Bullet")
    if section.table:
        _add_table(document, section.table)
    if section.significant_alerts:
        _add_significant_alerts(document, section.significant_alerts)
    for sub in section.subsections:
        _render_subsection(document, sub)


def _add_cover(document: Document, spec: ReportSpecification) -> None:
    if LOGO_PATH.exists():
        logo_p = document.add_paragraph()
        run = logo_p.add_run()
        run.add_picture(str(LOGO_PATH), height=Inches(0.6))

    badge = document.add_paragraph()
    badge_run = badge.add_run(spec.document_control.clasificacion)
    badge_run.bold = True
    badge_run.font.size = Pt(9)
    badge_run.font.color.rgb = MUTED

    document.add_paragraph()
    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("Informe de Gestión")
    run.bold = True
    run.font.size = Pt(28)
    run.font.color.rgb = DARK_GREEN
    run.font.highlight_color = WD_COLOR_INDEX.TURQUOISE

    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run("Servicio de Monitoreo SOC")
    run.font.size = Pt(16)
    run.font.color.rgb = DARK_GREEN
    run.font.highlight_color = WD_COLOR_INDEX.TURQUOISE

    # Lightweight nod to the template's curved brand banner -- a solid divider
    # bar, not an attempt at the original's decorative curve/photo collage.
    bar = document.add_table(rows=1, cols=1)
    _shade_cell(bar.rows[0].cells[0], "00532A")
    bar.rows[0].cells[0].paragraphs[0].add_run(" ")
    bar.rows[0].height = Pt(10)

    document.add_paragraph()
    company = document.add_paragraph()
    company.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = company.add_run(spec.company)
    run.font.size = Pt(20)
    run.bold = True
    run.font.color.rgb = DARK_GREEN

    period = document.add_paragraph()
    period.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = period.add_run(f"{spec.period.start} al {spec.period.end}")
    run.font.size = Pt(13)
    run.font.color.rgb = MUTED
    document.add_page_break()


def _add_document_control(document: Document, spec: ReportSpecification) -> None:
    document.add_heading("Control de Documento", level=1)
    dc = spec.document_control
    table = document.add_table(rows=4, cols=2)
    table.style = "Table Grid"
    rows_data = [
        ("Título", dc.titulo),
        ("Autor", dc.autor),
        ("Versión", str(dc.version)),
        ("Fecha de versión", dc.fecha_version),
    ]
    for i, (label, value) in enumerate(rows_data):
        _set_cell_text(table.rows[i].cells[0], label, bold=True, color=WHITE)
        _shade_cell(table.rows[i].cells[0], "00532A")
        table.rows[i].cells[1].text = value
    note = document.add_paragraph()
    run = note.add_run(dc.nota)
    run.italic = True
    run.font.color.rgb = MUTED
    document.add_page_break()


def build_document(spec: ReportSpecification, output_path: Path) -> Path:
    document = Document()
    _style_document(document)
    _add_page_header(document)
    _add_page_footer(document, spec)

    _add_cover(document, spec)
    _add_document_control(document, spec)

    document.add_heading("Tabla de Contenido", level=1)
    _add_toc(document)
    document.add_page_break()

    document.add_heading("1. Objetivo", level=1)
    _add_summary_paragraph(document, spec.objective)

    document.add_heading("2. Servicios", level=1)
    if spec.services:
        for s in spec.services:
            document.add_paragraph(s, style="List Bullet")
    else:
        _add_unavailable_notice(document, "No se identificaron servicios en el período consultado.")

    for section in spec.sections:
        _render_section(document, section)

    document.add_heading("11. Recomendaciones", level=1)
    for finding in spec.recommendations:
        p = document.add_paragraph(style="List Bullet")
        p.add_run(finding.statement)
        if finding.evidence and finding.evidence.source_alarm_numbers:
            cite = p.add_run(f"  ({', '.join(finding.evidence.source_alarm_numbers)})")
            cite.italic = True
            cite.font.color.rgb = MUTED

    _set_document_update_fields(document)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(output_path))
    return output_path
