"""Domain models for security alert data.

NormalizedSecurityAlert is the canonical shape every DataProvider returns,
whether the underlying source is the synthetic mock dataset or a real
client's alarm export (delivered by the remote alarm source over HTTP). Severity is a
1-100 score (matching the source business's own scale); RiskLevel is the
categorical tier derived from it via `risk_level_from_score`, mirroring the
client's own published thresholds (see data/mitre_tactics.json's sibling,
the Criticidad sheet, for where those thresholds came from).
"""
from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel


class RiskLevel(StrEnum):
    CRITICO = "Critico"
    ALTO = "Alto"
    MEDIO = "Medio"
    BAJO = "Bajo"
    ANULADO = "Anulado"


def risk_level_from_score(score: int | None) -> RiskLevel:
    """Client's actual thresholds, verified against their own Riesgo labels in the
    source data (the Criticidad sheet's printed ranges read as inclusive at the
    boundary, e.g. "50% al 69%" = Medio, but every real row with severity exactly
    50/70/90 is labeled the tier below -- so the true rule is a strict '>'):
    Critico >90, Alto >70, Medio >50, Bajo 1-50.
    """
    if score is None:
        return RiskLevel.ANULADO
    if score > 90:
        return RiskLevel.CRITICO
    if score > 70:
        return RiskLevel.ALTO
    if score > 50:
        return RiskLevel.MEDIO
    return RiskLevel.BAJO


class NotificationType(StrEnum):
    EMAIL = "email"
    SLACK = "slack"
    SMS = "sms"
    TICKET = "ticket"


class NotificationStatus(StrEnum):
    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    FAILED = "failed"


class Company(BaseModel):
    id: str
    name: str
    industry: str = "No especificado"
    country: str = "No especificado"
    # Fields of the client's official company list (data/companies.json,
    # persisted in in_companies) -- see app/services/company_registry.py.
    logo_key: str | None = None
    consecutivo: str | None = None
    source_client: str | None = None

    @property
    def request_client_name(self) -> str:
        """Value sent as `cliente=` to the data source."""
        return self.source_client or self.name


class Notification(BaseModel):
    id: str
    alert_id: str
    notification_type: NotificationType
    timestamp: datetime
    status: NotificationStatus


class PersonRef(BaseModel):
    name: str | None = None
    role: str | None = None
    contact: str | None = None


class EscalationFlags(BaseModel):
    called: bool = False
    glpi_ticket: bool = False
    sharepoint_doc: bool = False


class NormalizedSecurityAlert(BaseModel):
    # Identity
    id: str
    alarm_number: str
    original_id: str | None = None
    client: str

    # Classification
    alert_type: str
    category: str
    severity_score: int | None
    risk_level: RiskLevel
    is_voided: bool = False

    # Technical event
    event_timestamp: datetime
    created_at: datetime
    reported_at: datetime
    source_ips: list[str] = []
    external_ips: list[str] = []
    hostnames: list[str] = []
    description: str
    url: str | None = None

    # MITRE ATT&CK
    mitre_tactic_id: str | None = None
    mitre_tactic_name: str | None = None

    # SOC record
    reported_by: PersonRef | None = None
    authorized_by: PersonRef | None = None
    escalation: EscalationFlags = EscalationFlags()

    # Resolution
    recommendations: str | None = None
    response: str | None = None
    responded_at: datetime | None = None
    status: str = "open"  # "open" | "resolved", derived from response presence

    # Traceability -- the original row/record is never discarded
    raw_record: dict = {}


class AlertMetrics(BaseModel):
    total_alerts: int
    critico_alerts: int
    alto_alerts: int
    medio_alerts: int
    bajo_alerts: int
    voided_alerts: int
    resolved_alerts: int
    open_alerts: int
    average_severity_score: float


class MitreTactic(BaseModel):
    id: str
    name_es: str
    description_es: str
    is_custom: bool = False


class EmailRarityEntry(BaseModel):
    email: str
    count: int


# ---- Source indicators page (indicadores.php) -------------------------------------


class IndicatorCount(BaseModel):
    label: str
    count: int


class RiskShare(BaseModel):
    """One row of the source's own "Tabla de Riesgo por Severidad". Note: the
    source's dashboard uses its own severity bands (e.g. 0-25/26-50/51-75/76-100),
    which are not the bands the report classifies alarms with."""

    level: str
    range_label: str | None = None
    percent: float


class IndicatorRecord(BaseModel):
    """One alarm as listed (in reduced form) by the indicators page."""

    alert_type: str
    timestamp: datetime | None = None
    source_ip: str | None = None
    external_ip: str | None = None
    hostname: str | None = None
    description: str = ""
    reported_by: str | None = None
    created_at: datetime | None = None
    severity_score: int | None = None


class SourceIndicators(BaseModel):
    """Everything the source's indicators page states for one client/period."""

    client: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    total_alarms: int
    principal_source_ip: str | None = None
    risk_distribution: list[RiskShare] = []
    alarms_by_type: list[IndicatorCount] = []
    alarms_by_day: list[IndicatorCount] = []
    top_categories: list[IndicatorCount] = []
    top_source_ips: list[IndicatorCount] = []
    top_destination_ips: list[IndicatorCount] = []
    top_hostnames: list[IndicatorCount] = []
    top_descriptions: list[IndicatorCount] = []
    records: list[IndicatorRecord] = []
    available_clients: list[str] = []
    warnings: list[str] = []
