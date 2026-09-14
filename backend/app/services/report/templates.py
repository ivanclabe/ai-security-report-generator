"""Report template registry (see ARCHITECTURE_TARGET.md §3.1 and §9 -- a plain
callable registry, not a class hierarchy or DSL: there is exactly one template
today, and generalizing the abstraction before a second real template exists
would be guessing at a shape nobody has asked for yet.

Adding a new report type later means writing one function with this same
signature and calling register_template() -- nothing else in the pipeline
(specification.py, the agent, the future deterministic endpoint) changes.
"""
from typing import Callable

from app.schemas.report_spec import Section, SignificantAlert, SimpleTable, Subsection
from app.services.report.narrative import (
    DISCONNECTED_CATEGORY,
    EMAIL_TYPE,
    NETWORK_TYPE,
    SIEM_TYPE,
    THREAT_INTEL_TYPES,
    ReportNarrative,
)

TemplateBuilder = Callable[[dict, ReportNarrative], list[Section]]

_REGISTRY: dict[str, TemplateBuilder] = {}
DEFAULT_TEMPLATE_KEY = "csoc_mensual"


def register_template(key: str, builder: TemplateBuilder) -> None:
    _REGISTRY[key] = builder


def get_template(key: str | None) -> TemplateBuilder:
    resolved = key or DEFAULT_TEMPLATE_KEY
    if resolved not in _REGISTRY:
        raise ValueError(f"Unknown report template: {resolved}")
    return _REGISTRY[resolved]


def _dominant_risk(alerts: list[dict]) -> str:
    from collections import Counter

    counts = Counter(a["risk_level"] for a in alerts)
    return counts.most_common(1)[0][0] if counts else "-"


def _source_events_table(alerts: list[dict], alert_type: str) -> SimpleTable | None:
    subset = [a for a in alerts if a.get("alert_type") == alert_type]
    if not subset:
        return None
    by_category: dict[str, list[dict]] = {}
    for a in subset:
        by_category.setdefault(a["category"], []).append(a)
    rows = [
        [category, _dominant_risk(items), str(len(items))]
        for category, items in sorted(by_category.items(), key=lambda kv: len(kv[1]), reverse=True)
    ]
    return SimpleTable(headers=["Categoría", "Riesgo predominante", "Cantidad"], rows=rows)


def _top_significant_alerts(alerts: list[dict], alert_type: str, n: int = 1) -> list[SignificantAlert]:
    subset = [a for a in alerts if a.get("alert_type") == alert_type and not a.get("is_voided")]
    subset.sort(key=lambda a: a.get("severity_score") or 0, reverse=True)
    return [
        SignificantAlert(
            alarm_number=a["alarm_number"],
            heading=a["alarm_number"],
            description=a.get("description") or "",
            response=a.get("response"),
        )
        for a in subset[:n]
    ]


def _disconnected_agents_table(alerts: list[dict]) -> SimpleTable | None:
    """One row per distinct host, not per alarm -- the same server is often flagged
    disconnected across several alarms in a month, and 'estado de agentes' should read
    as current per-asset status, not a raw log of every individual disconnect event."""
    subset = [a for a in alerts if a.get("category") == DISCONNECTED_CATEGORY]
    if not subset:
        return None
    by_host: dict[str, dict] = {}
    for a in subset:
        hostnames = a.get("hostnames") or ["-"]
        host = hostnames[0]
        ips = a.get("source_ips") or a.get("external_ips") or ["-"]
        entry = by_host.setdefault(host, {"ip": ips[0] if ips else "-", "alarm_numbers": []})
        entry["alarm_numbers"].append(a["alarm_number"])
    rows = [[host, info["ip"], ", ".join(info["alarm_numbers"])] for host, info in sorted(by_host.items())]
    return SimpleTable(headers=["Servidor", "IP", "Alarmas asociadas"], rows=rows)


def _disconnected_agents_subsection(alerts: list[dict]) -> Subsection:
    # No rows here is a real (positive) finding, not a missing-data-source case --
    # keep it "available" and say so in prose, don't render it like the 7.1/7.2 notices.
    table = _disconnected_agents_table(alerts)
    return Subsection(
        number="3.3",
        title="Estado Agentes Monitoreados SIEM/EDR",
        table=table,
        summary=None if table is not None else "No se reportaron agentes desconectados en el período.",
    )


def _risk_breakdown_table(metrics: dict) -> SimpleTable:
    total = metrics.get("total_alerts", 0) - metrics.get("voided_alerts", 0)
    rows = []
    for label, key in [("Crítico", "critico_alerts"), ("Alto", "alto_alerts"), ("Medio", "medio_alerts"), ("Bajo", "bajo_alerts")]:
        count = metrics.get(key, 0)
        pct = round((count / total) * 100, 1) if total else 0.0
        rows.append([label, str(count), f"{pct}%"])
    return SimpleTable(headers=["Nivel de riesgo", "Cantidad", "% Participación"], rows=rows)


def _trend_table(trends_3mo: list[dict]) -> SimpleTable:
    rows = [[t["period"], str(t["total_alerts"]), str(t["critico_alerts"])] for t in trends_3mo]
    return SimpleTable(headers=["Período", "Total alarmas", "Críticas"], rows=rows)


def _email_rarity_table(entries: list[dict]) -> SimpleTable:
    rows = [[e["email"], str(e["count"])] for e in entries[:10]]
    return SimpleTable(headers=["Usuario", "Cantidad recibidos"], rows=rows)


def _data_leak_table(entries: list[dict]) -> SimpleTable:
    rows = [[e["sender"], str(e["count"])] for e in entries[:10]]
    return SimpleTable(headers=["Remitente", "Cantidad"], rows=rows)


def _ip_table(entries: list[dict]) -> SimpleTable:
    rows = [[e["ip"], str(e["count"]), e["alarm_numbers"][0] if e["alarm_numbers"] else "-"] for e in entries]
    return SimpleTable(headers=["IP", "Alarmas", "Ejemplo de alarma"], rows=rows)


def build_csoc_mensual_sections(collected: dict, narrative: ReportNarrative) -> list[Section]:
    """The only template registered today -- an 11-section skeleton matching the
    client's own recurring "Informe de Gestión CSOC" Word template. Moved verbatim
    from the old generate_report_spec.py."""
    alerts = collected.get("alerts", [])

    email = collected.get("email_summary", {})
    email_subsections = [
        Subsection(
            number="6.1",
            title="Top 10 Usuarios Con Mayor Tráfico De Correos Maliciosos Entrantes",
            table=_email_rarity_table(email.get("top_rarity_recipients", [])),
            available=email.get("rarity_data_available", False),
            unavailable_reason=None
            if email.get("rarity_data_available")
            else "No disponible: la fuente de datos actual no incluye el detalle de índice de rareza de correos.",
        ),
        Subsection(
            number="6.2",
            title="Top 10 Correos Con Mayor Índice De Rareza Del 96% Al 100%",
            available=False,
            unavailable_reason="No disponible: requiere el detalle de asunto por correo sospechoso, no incluido en la fuente de datos actual.",
        ),
        Subsection(
            number="6.3",
            title="Top 10 Usuarios De Posible Fuga De Información",
            table=_data_leak_table(email.get("data_leak_senders", [])),
            summary=None if email.get("data_leak_senders") else "No se identificaron casos de posible fuga de información en el período.",
            available=True,
        ),
        Subsection(
            number="6.4",
            title="Alarmas Significativas Antígeno Correo",
            significant_alerts=_top_significant_alerts(alerts, EMAIL_TYPE),
        ),
    ]

    ip_indicators = collected.get("ip_indicators", {})
    return [
        Section(
            number="3",
            title="Inventario Monitoreado",
            summary=narrative.inventory_summary,
            subsections=[
                Subsection(
                    number="3.1",
                    title="Estadística de Alarmas Últimos Tres Meses",
                    table=_trend_table(collected.get("trends_3mo", [])),
                    summary=None
                    if len(collected.get("trends_3mo", [])) >= 3
                    else "Nota: la fuente de datos actual solo cubre el período indicado; no hay historial completo de 3 meses.",
                ),
                Subsection(number="3.2", title="Indicadores Alarmas", table=_risk_breakdown_table(collected.get("metrics", {}))),
                _disconnected_agents_subsection(alerts),
            ],
        ),
        Section(
            number="4",
            title="Gestión Alarmas SIEM",
            summary=narrative.siem_summary,
            subsections=[
                Subsection(number="4.1", title="Eventos SIEM", table=_source_events_table(alerts, SIEM_TYPE)),
                Subsection(number="4.2", title="Alarma Significativa", significant_alerts=_top_significant_alerts(alerts, SIEM_TYPE)),
            ],
        ),
        Section(
            number="5",
            title="Antígeno de Red",
            summary=narrative.network_summary,
            subsections=[
                Subsection(number="5.1", title="Eventos Antígeno de Red", table=_source_events_table(alerts, NETWORK_TYPE)),
                Subsection(
                    number="5.2",
                    title="Alarmas Significativas Antígeno de Red",
                    significant_alerts=_top_significant_alerts(alerts, NETWORK_TYPE),
                ),
            ],
        ),
        Section(number="6", title="Antígeno de Correo", summary=narrative.email_summary, subsections=email_subsections),
        Section(
            number="7",
            title="Inteligencia de Amenazas",
            summary=narrative.threat_intel_summary,
            subsections=[
                Subsection(
                    number="7.1",
                    title="Monitoreo de Marca",
                    available=False,
                    unavailable_reason="No disponible: requiere integración con una plataforma de monitoreo de marca; no incluida en las fuentes de datos actuales.",
                ),
                Subsection(
                    number="7.2",
                    title="Vulnerabilidades",
                    available=False,
                    unavailable_reason="No disponible: requiere un feed de gestión de vulnerabilidades (ej. CrowdStrike Spotlight); no incluido en las fuentes de datos actuales.",
                ),
                Subsection(
                    number="7.3",
                    title="Alarmas Inteligencia De Amenazas",
                    table=SimpleTable(
                        headers=["Tipo", "Riesgo predominante", "Cantidad"],
                        rows=[
                            [t, _dominant_risk([a for a in alerts if a.get("alert_type") == t]), str(sum(1 for a in alerts if a.get("alert_type") == t))]
                            for t in THREAT_INTEL_TYPES
                            if any(a.get("alert_type") == t for a in alerts)
                        ],
                    ),
                ),
                Subsection(
                    number="7.4",
                    title="Alarmas Significativas Inteligencia De Amenazas",
                    significant_alerts=[
                        alert
                        for t in THREAT_INTEL_TYPES
                        for alert in _top_significant_alerts(alerts, t)
                    ],
                ),
            ],
        ),
        Section(
            number="8",
            title="Análisis de Comportamiento",
            available=False,
            unavailable_reason="No disponible: requiere una plataforma de análisis de comportamiento (UEBA); no incluida en las fuentes de datos actuales.",
        ),
        Section(
            number="9",
            title="Indicadores de Compromiso",
            summary=narrative.compromise_indicators_summary,
            subsections=[
                Subsection(number="9.1", title="Top IPs Origen", table=_ip_table(ip_indicators.get("top_source_ips", []))),
                Subsection(number="9.2", title="Top IPs Destino", table=_ip_table(ip_indicators.get("top_external_ips", []))),
                Subsection(number="9.3", title="Gestión de Alarmas por Mes", table=_trend_table(collected.get("trends_3mo", []))),
            ],
        ),
        Section(
            number="10",
            title="Actividades Destacadas",
            body=narrative.highlighted_activities,
        ),
    ]


register_template(DEFAULT_TEMPLATE_KEY, build_csoc_mensual_sections)
