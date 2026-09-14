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
    clasificacion: str = "CONFIDENCIAL"


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


class Subsection(BaseModel):
    number: str
    title: str
    summary: str | None = None
    body: list[str] = Field(default_factory=list)
    table: SimpleTable | None = None
    significant_alerts: list[SignificantAlert] = Field(default_factory=list)
    available: bool = True
    unavailable_reason: str | None = None


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


class ReportSpecification(BaseModel):
    document_control: DocumentControl
    company: str
    period: ReportPeriod
    objective: str
    services: list[str] = Field(default_factory=list)
    sections: list[Section]
    recommendations: list[KeyFinding] = Field(default_factory=list)

    def validate_business_rules(self) -> list[str]:
        errors: list[str] = []
        if not self.sections:
            errors.append("Report specification must contain at least one section.")
        if not self.recommendations:
            errors.append("Report specification must contain at least one recommendation.")
        return errors

    def _iter_evidence(self):
        for section in self.sections:
            for a in section.significant_alerts:
                yield section.number, a.alarm_number
            for sub in section.subsections:
                for a in sub.significant_alerts:
                    yield sub.number, a.alarm_number
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
