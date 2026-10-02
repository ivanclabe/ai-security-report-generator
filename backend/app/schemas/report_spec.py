"""The intermediate ReportSpecification -- now shaped for a Word (.docx)
management report, matching the client's own recurring "Informe de Gestión
CSOC" template (fixed section skeleton, not an LLM-chosen slide deck).

Unlike the LLM writing narrative strings, the SECTION STRUCTURE itself is
assembled deterministically in generate_report_spec.py from tool output --
the LLM only ever fills `summary` prose fields, never decides what sections
exist, what a table contains, or whether a section is "available". This is
still the same invariant as before: the document builder (docx_builder.py)
consumes only this validated, code-assembled Pydantic object, never raw LLM
output directly.
"""
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class ReportPeriod(BaseModel):
    start: str
    end: str


class DocumentControl(BaseModel):
    titulo: str
    autor: str = "Generado automáticamente por AI Security Report Generator"
    version: int = 1
    fecha_version: str
    nota: str = "Documento generado automáticamente. Pendiente de revisión y aprobación humana antes de su distribución oficial."
    # Footer/cover metadata matching the client's own template (form code, template
    # version, classification) -- defaults mirror the file they shared as the format
    # to follow; adjust if their real document-control system uses different values.
    codigo_documento: str = "GCB-FR-14"
    version_plantilla: str = "03"
    fecha_plantilla: str = "23/05/2025"
    clasificacion: str = "SECRETO"
    # Review workflow of the client's template: filled by people, never by the app.
    revisado_por: str = "Pendiente"
    revisado_por_2: str = "Pendiente"
    aprobado_por: str = "Pendiente"
    fecha_revision: str = "Pendiente"
    fecha_aprobacion: str = "Pendiente"


class SimpleTable(BaseModel):
    headers: list[str]
    rows: list[list[str]] = Field(default_factory=list)


class SignificantAlert(BaseModel):
    alarm_number: str
    heading: str
    description: str
    response: str | None = None


class EvidenceRef(BaseModel):
    source_alarm_numbers: list[str] = Field(default_factory=list)
    metric: str | None = None


class KeyFinding(BaseModel):
    statement: str
    evidence: EvidenceRef | None = None


# ---- content blocks -----------------------------------------------------------------------
# The layout of the client's reference report, as data: the template (templates.py) decides
# which blocks a section has and fills them ONLY from computed facts (csoc_facts.py); the
# document builder only draws them.


class Cell(BaseModel):
    text: str
    fill: str | None = None  # hex RGB, e.g. "E2EFD9"
    bold: bool = False
    color: str | None = None  # text hex RGB
    align: Literal["left", "center", "right"] = "left"
    colspan: int = 1


class ParagraphBlock(BaseModel):
    kind: Literal["paragraph"] = "paragraph"
    text: str
    bold_terms: list[str] = Field(default_factory=list)  # substrings rendered in bold
    style: Literal["normal", "caption"] = "normal"


class MinorHeadingBlock(BaseModel):
    kind: Literal["minor_heading"] = "minor_heading"
    text: str


class BulletsBlock(BaseModel):
    kind: Literal["bullets"] = "bullets"
    items: list[str]


class NoticeBlock(BaseModel):
    """Explicit "no evidence" statement where the reference shows something the data cannot support."""

    kind: Literal["notice"] = "notice"
    text: str


class TableBlock(BaseModel):
    kind: Literal["table"] = "table"
    header_rows: list[list[Cell]]
    rows: list[list[Cell]] = Field(default_factory=list)
    widths: list[float] | None = None  # inches per column
    font_size: float = 10.5


class ChartSeries(BaseModel):
    name: str
    values: list[float]
    color: str  # hex RGB


class ChartBlock(BaseModel):
    kind: Literal["chart"] = "chart"
    chart: Literal["bar", "grouped_bar", "hbar", "radar", "line"]
    title: str
    categories: list[str]
    series: list[ChartSeries]
    x_label: str | None = None
    y_label: str | None = None
    width_inches: float = 6.3
    height_inches: float = 3.2


class AlertBoxBlock(BaseModel):
    """A significant alarm: description, the event's data sheet and the registered response."""

    kind: Literal["alert_box"] = "alert_box"
    alarm_number: str
    description: str
    event_info: list[tuple[str, str]] = Field(default_factory=list)
    risk_level: str | None = None
    recommendation: str | None = None
    response: str | None = None
    responded_at: str | None = None


class ServiceTilesBlock(BaseModel):
    kind: Literal["service_tiles"] = "service_tiles"
    services: list[str]


class SideBySideBlock(BaseModel):
    kind: Literal["side_by_side"] = "side_by_side"
    titles: tuple[str, str]
    left: TableBlock
    right: TableBlock


Block = Annotated[
    ParagraphBlock | MinorHeadingBlock | BulletsBlock | NoticeBlock | TableBlock | ChartBlock | AlertBoxBlock
    | ServiceTilesBlock | SideBySideBlock,
    Field(discriminator="kind"),
]


class Subsection(BaseModel):
    number: str
    title: str
    summary: str | None = None
    body: list[str] = Field(default_factory=list)
    table: SimpleTable | None = None
    significant_alerts: list[SignificantAlert] = Field(default_factory=list)
    available: bool = True
    unavailable_reason: str | None = None
    blocks: list[Block] = Field(default_factory=list)


class Section(BaseModel):
    number: str
    title: str
    summary: str | None = None
    body: list[str] = Field(default_factory=list)
    table: SimpleTable | None = None
    significant_alerts: list[SignificantAlert] = Field(default_factory=list)
    subsections: list[Subsection] = Field(default_factory=list)
    available: bool = True
    unavailable_reason: str | None = None
    blocks: list[Block] = Field(default_factory=list)


class ReportSpecification(BaseModel):
    document_control: DocumentControl
    company: str
    company_logo: str | None = None  # registry logo key (see docx_builder.resolve_logo_path)
    period: ReportPeriod
    objective: str
    services: list[str] = Field(default_factory=list)
    sections: list[Section]
    recommendations: list[KeyFinding] = Field(default_factory=list)
    # Facts every figure of the document comes from (csoc_facts.build_facts), kept with the
    # version so any statement can be traced back; and what validation removed, if anything.
    facts: dict = Field(default_factory=dict)
    validation_notes: list[str] = Field(default_factory=list)

    def validate_business_rules(self) -> list[str]:
        errors: list[str] = []
        if not self.sections:
            errors.append("Report specification must contain at least one section.")
        # No recommendation is a valid outcome: when none is backed by the data, the document
        # says so explicitly (chapter 11) instead of inventing one.
        return errors

    def _iter_evidence(self):
        for section in self.sections:
            for a in section.significant_alerts:
                yield section.number, a.alarm_number
            for block in section.blocks:
                if isinstance(block, AlertBoxBlock):
                    yield section.number, block.alarm_number
            for sub in section.subsections:
                for a in sub.significant_alerts:
                    yield sub.number, a.alarm_number
                for block in sub.blocks:
                    if isinstance(block, AlertBoxBlock):
                        yield sub.number, block.alarm_number
        for finding in self.recommendations:
            if finding.evidence:
                for n in finding.evidence.source_alarm_numbers:
                    yield "recomendaciones", n

    def validate_evidence(self, known_alarm_numbers: set[str]) -> list[str]:
        """Every cited alarm_number must be one the agent actually collected --
        catches a fabricated citation before it reaches the user."""
        errors: list[str] = []
        for location, alarm_number in self._iter_evidence():
            if alarm_number not in known_alarm_numbers:
                errors.append(f"Section '{location}' cites unknown alarm number: {alarm_number}")
        return errors
