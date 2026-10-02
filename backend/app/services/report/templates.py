"""Report template registry + the "Informe de Gestión CSOC" template.

A template turns the collected data into the report's sections. The CSOC
template reproduces the structure and presentation of the client's own
reference report (TGS TPS Informe de Gestión CSOC, form GCB-FR-14): the same
chapters and subsections, in the same order, with the same kinds of tables
and charts. Its CONTENT comes exclusively from the data: every figure, table
row and chart value is computed in csoc_facts.py from the alarms of the
period; where the reference shows something the data sources cannot support
(asset inventory, console screenshots, vulnerability or brand monitoring
feeds, IP reputation), the section says so explicitly instead of filling it.
The LLM writes nothing here -- only the recommendations (chapter 11), which
validation.py checks against these same facts.

Adding a report type = one more builder function + register_template().
"""
from collections.abc import Callable
from datetime import date, datetime

from app.schemas.report_spec import (
    AlertBoxBlock,
    BulletsBlock,
    Cell,
    ChartBlock,
    ChartSeries,
    MinorHeadingBlock,
    NoticeBlock,
    ParagraphBlock,
    Section,
    SideBySideBlock,
    Subsection,
    TableBlock,
)
from app.services.report import csoc_facts as f
from app.services.report.narrative import ReportNarrative

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


# ---- presentation constants of the reference report -------------------------------------------

HEADER = "0B5D33"
LIGHT_GREEN = "E2EFD9"
GRAY = "D9D9D9"
WHITE = "FFFFFF"
RISK_FILL = {"Critico": "C00000", "Alto": "FF0000", "Medio": "FFC000", "Bajo": "00B050"}
BAR_DARK = "0A3D1C"
TEAL = "00706E"
AMBER = "FFC000"

SERVICE_ROW_LABEL = {
    f.SIEM: "Número de alarmas revisadas por el equipo CSOC en correlacionador SIEM",
    f.CORREO: "Número de alarmas revisadas por el equipo CSOC por el antígeno de correo",
    f.RED: "Número de alarmas revisadas por el equipo CSOC por el antígeno de red",
    f.INTEL: "Número de alarmas revisadas por el equipo CSOC de Inteligencia de amenazas",
    f.ZABBIX: "Número de alarmas revisadas por el equipo CSOC de ZABBIX",
}
EVIDENCE = "Export de alarmas"
NO_DATA = "N/D"


def _h(text: str, colspan: int = 1) -> Cell:
    return Cell(text=text, fill=HEADER, bold=True, color=WHITE, align="center", colspan=colspan)


def _c(text, **kwargs) -> Cell:
    return Cell(text=str(text), **kwargs)


def _risk(risk: str, upper: bool = False) -> Cell:
    if risk not in RISK_FILL:
        return _c(risk or "-", align="center")
    label = f.RISK_LABEL[risk]
    return Cell(text=label.upper() if upper else label, fill=RISK_FILL[risk], color=WHITE, bold=True, align="center")


def _join(items: list[str]) -> str:
    return ", ".join(items[:-1]) + " y " + items[-1] if len(items) > 1 else "".join(items)


def _notice(what: str) -> NoticeBlock:
    return NoticeBlock(text=f"No se encontró evidencia suficiente en las fuentes de datos disponibles para {what}.")


def _when(alert: dict) -> datetime:
    return datetime.fromisoformat(str(alert.get("created_at") or alert.get("event_timestamp")).replace("Z", "+00:00"))


def _day_month(d: datetime) -> str:
    return f"{d.day:02d}-{f.MONTHS_SHORT[d.month - 1].lower()}"


def _alert_box(alert: dict) -> AlertBoxBlock:
    def joined(values) -> str:
        return ", ".join(f._split(values)) or "N/A"

    tactic = " ".join(p for p in (alert.get("mitre_tactic_id"), alert.get("mitre_tactic_name")) if p) or "N/A"
    score = alert.get("severity_score")
    description = " ".join((alert.get("description") or "").replace("_x000D_", " ").split())
    response = " ".join((alert.get("response") or "").replace("_x000D_", " ").split()) or None
    responded = alert.get("responded_at")
    return AlertBoxBlock(
        alarm_number=alert["alarm_number"],
        description=description or "La alarma no registra descripción en la fuente.",
        risk_level=alert.get("risk_level"),
        event_info=[
            ("Riesgo evento", f.RISK_LABEL.get(alert.get("risk_level"), alert.get("risk_level") or "N/A")),
            ("Clasificación % riesgo", f"{score}%" if score is not None else "N/A"),
            ("Host", joined(alert.get("hostnames"))),
            ("Tipo", alert.get("alert_type") or "N/A"),
            ("Alarma tipo", alert.get("category") or "N/A"),
            ("Dirección IP origen", joined(alert.get("source_ips"))),
            ("Táctica MITRE", tactic),
            ("Fecha de creación", _when(alert).strftime("%d/%m/%Y %H:%M")),
            ("Dirección IP destino", joined(alert.get("external_ips"))),
        ],
        recommendation=" ".join((alert.get("recommendations") or "").replace("_x000D_", " ").split()) or None,
        response=response,
        responded_at=datetime.fromisoformat(str(responded).replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M")
        if responded
        else None,
    )


def _significant(alerts: list[dict], service: str, intro: str, empty: str) -> list:
    alert = f.significant_alert(f.of_service(alerts, service))
    if alert is None:
        return [ParagraphBlock(text=empty)]
    return [
        ParagraphBlock(text=intro),
        _alert_box(alert),
        ParagraphBlock(text="Criterio de selección: alarma con el mayor puntaje de severidad del período en este servicio.",
                       style="caption"),
    ]


# ---- chapters ------------------------------------------------------------------------------------------


def _inventory(ctx: dict) -> Section:
    alerts, facts, history = ctx["alerts"], ctx["facts"], ctx["history"]
    months = history.get("months", [])
    month_labels = [f.month_label(m["month"]) for m in months]
    present = set().union(*(m["services"].keys() for m in months)) if months else set()
    services = [s for s in f.ordered_services(present)]

    # 3.1 -- last three months per service
    available = [f.has_records(m) for m in months]
    missing = [label for label, ok in zip(month_labels, available) if not ok]
    rows = []
    for service in services + [f.ANULADAS]:
        values = [m["services"].get(service, 0) if service != f.ANULADAS else m["voided"] for m in months]
        if service == f.ANULADAS and not any(values):
            continue
        label = SERVICE_ROW_LABEL.get(service, "Anuladas" if service == f.ANULADAS else f"Número de alarmas de {service}")
        # the trend compares the last two months only when the source has data for both
        trend = f.trend_arrow(values[-2], values[-1]) if len(values) >= 2 and all(available[-2:]) else NO_DATA
        rows.append([
            _c(label),
            *[_c(v if ok else NO_DATA, fill=LIGHT_GREEN, bold=True, align="center") for v, ok in zip(values, available)],
            _c(trend, align="center", bold=True),
            _c(EVIDENCE, align="center"),
        ])
    three_months_table = TableBlock(
        header_rows=[
            [_h("Comportamiento de alarmas"), _h("Valor", colspan=len(months)), _h("Tendencia"), _h("Evidencia")],
            [_h(""), *[_h(label) for label in month_labels], _h(""), _h("")],
        ],
        rows=rows,
        widths=[2.9, *([0.62] * len(months)), 0.85, 0.95],
    )
    variation_chart = ChartBlock(
        chart="bar",
        title=f"Indicador de variación alarmas mes a mes {ctx['company']}",
        categories=[label for label, ok in zip(month_labels, available) if ok],
        series=[ChartSeries(name="Total alarmas", values=[m["effective"] for m in months if f.has_records(m)],
                            color=BAR_DARK)],
        y_label="Cantidad de alarmas",
        height_inches=3.0,
    )

    # 3.2 -- indicators of the period
    by_service = facts["alarms_by_service"]
    parts = [f"{s} ({by_service[s]})" for s in services if by_service.get(s)]
    if facts["voided_alarms"]:
        parts.append(f"Anuladas ({facts['voided_alarms']})")
    total_label = f"total de {facts['effective_alarms']} alarmas"
    indicators_text = (
        f"Durante el período {ctx['period_phrase']} se registraron un total de {facts['total_alarms']} alarmas, "
        f"distribuidas en {', '.join(parts[:-1]) + ' y ' + parts[-1] if len(parts) > 1 else ''.join(parts)}, "
        f"para un {total_label} efectivamente procesadas para {ctx['company']}. "
        f"Se observa que {facts['answered']} alarmas fueron atendidas y {facts['unanswered']} se encuentran sin respuesta."
    )
    responses = f.response_by_service(alerts)
    response_chart = ChartBlock(
        chart="grouped_bar",
        title=f"Indicador alarmas {ctx['period_title']}",
        categories=[r["service"].upper() for r in responses] + ["TOTAL"],
        series=[
            ChartSeries(name="Con respuesta", values=[r["answered"] for r in responses] + [facts["answered"]], color=TEAL),
            ChartSeries(name="Sin respuesta", values=[r["unanswered"] for r in responses] + [facts["unanswered"]], color=AMBER),
        ],
        height_inches=3.1,
    )
    risk = facts["risk_distribution"]
    risk_table = TableBlock(
        header_rows=[[_h("RIESGO"), _h(ctx["month_name"]), _h("% Participación")]],
        rows=[[_risk(r, upper=True), _c(risk[r], align="center"), _c(f"{facts['risk_percent'][r]}%", align="center")]
              for r in f.RISK_ORDER],
        widths=[2.9, 2.0, 1.4],
    )
    totals = {r: sum(m["risk"][r] for m in months if f.has_records(m)) for r in f.RISK_ORDER}
    grand = sum(totals.values())
    histogram = TableBlock(
        header_rows=[[_h("RIESGO"), *[_h(f.month_label(m["month"], short=False)) for m in months], _h("TOTAL"),
                      _h("% Global")]],
        rows=[[_risk(r, upper=True),
               *[_c(m["risk"][r] if f.has_records(m) else NO_DATA, align="center") for m in months],
               _c(totals[r], fill=GRAY, bold=True, align="center"), _c(f"{f.pct(totals[r], grand)}%", align="center")]
              for r in f.RISK_ORDER],
        widths=[1.4, *([1.0] * len(months)), 1.0, 1.0],
    )

    # 3.3 -- agents reported disconnected (from the alarms; the EDR inventory itself is not in the data)
    hosts = f.disconnected_agents(alerts)
    agents_blocks: list = [_notice("reportar el inventario de agentes del SIEM/EDR (equipos activos, inactivos e incompatibles)")]
    if hosts:
        agents_blocks += [
            ParagraphBlock(text=f"Se relacionan a continuación los {len(hosts)} servidores reportados con agente desconectado "
                                f"en las alarmas del período, para su validación interna:"),
            TableBlock(
                header_rows=[[_h("SERVIDOR"), _h("IP"), _h("OBSERVACIÓN")]],
                rows=[[_c(h["host"]), _c(h["ip"]), _c(f"Agente reportado desconectado / Última alarma {_day_month(h['last'])}",
                                                         align="center")] for h in hosts],
                widths=[1.7, 1.6, 3.1],
            ),
            ParagraphBlock(
                text="Las desconexiones fueron reportadas con las alarmas "
                     + f.compress_alarm_numbers(sorted({n for h in hosts for n in h["alarms"]}, key=f._alarm_sort_key,
                                                       reverse=True)) + "."
            ),
        ]
    else:
        agents_blocks.append(ParagraphBlock(text="No se reportaron alarmas de agentes desconectados en el período."))

    return Section(
        number="3",
        title="Inventario Monitoreado",
        blocks=[
            ParagraphBlock(text=f"Durante el período {ctx['period_phrase']} se realizó el monitoreo de {ctx['company']} a "
                                f"través de los servicios {', '.join(services) or 'del SOC'}, con {facts['total_alarms']} "
                                f"alarmas registradas en las fuentes de datos."),
            _notice("reportar las cifras de equipos activos descubiertos y vigilados en el EDR y en el SIEM, ni la "
                    "conectividad del firewall"),
        ],
        subsections=[
            Subsection(number="3.1", title="Estadística de Alarmas Últimos Tres Meses", blocks=[
                ParagraphBlock(text="Se relaciona el estadístico de alarmas durante los últimos tres meses, distribuidas de la "
                                    "siguiente manera:"),
                three_months_table,
                *([NoticeBlock(text=f"Las fuentes de datos no devolvieron alarmas para {_join(missing)}; esos meses se "
                                    f"muestran como {NO_DATA} y no se incluyen en la tendencia, el gráfico ni los totales.")]
                  if missing else []),
                ParagraphBlock(text=f"Se muestra el índice de variación mensual sobre el total de alarmas efectivas de "
                                    f"{ctx['company']} (sin contar las anuladas) reportadas en los últimos 3 meses:"),
                variation_chart,
            ]),
            Subsection(number="3.2", title="Indicadores Alarmas", blocks=[
                ParagraphBlock(text=indicators_text, bold_terms=[total_label]),
                response_chart,
                ParagraphBlock(
                    text=f"Durante el período {ctx['period_phrase']}, se notificaron {facts['effective_alarms']} alarmas, "
                         "debido a que las alarmas anuladas no se tienen en cuenta para el análisis de estadísticas del "
                         "informe; su clasificación de riesgo es la siguiente:",
                    bold_terms=[f"{facts['effective_alarms']} alarmas"],
                ),
                risk_table,
                ParagraphBlock(text="Histograma de la clasificación de las alarmas de acuerdo con el nivel de criticidad, "
                                    "durante los últimos tres meses:"),
                histogram,
            ]),
            Subsection(number="3.3", title="Estado Agentes Monitoreados SIEM/EDR", blocks=agents_blocks),
        ],
    )


def _siem(ctx: dict) -> Section:
    siem = f.effective(f.of_service(ctx["alerts"], f.SIEM))
    categories = f.categories_of(siem)
    blocks_41: list
    if siem:
        top = categories[:8]
        highlights = ", ".join(f"{n} de {c.lower()}" for c, n, _ in top[:3])
        blocks_41 = [
            ParagraphBlock(text="Durante el período monitoreado se identificaron diferentes alarmas, relacionando a "
                                "continuación los eventos más significativos:"),
            ChartBlock(chart="hbar", title="ALARMAS GENERADAS", categories=[c for c, _, _ in top],
                       series=[ChartSeries(name="Alarmas", values=[n for _, n, _ in top], color=TEAL)],
                       height_inches=max(2.2, 0.55 * len(top) + 1.0)),
            MinorHeadingBlock(text="Detalle de alarmas"),
            ParagraphBlock(text=f"Durante el período {ctx['period_phrase']} se registraron un total de {len(siem)} alarmas "
                                f"de SIEM, destacándose {highlights}."),
            TableBlock(header_rows=[[_h("Servicio"), _h("Riesgo"), _h("SIEM")]],
                       rows=[[_c(c), _risk(r), _c(n, align="center")] for c, n, r in categories],
                       widths=[2.9, 2.0, 1.4]),
        ]
    else:
        blocks_41 = [ParagraphBlock(text="No se registraron alarmas de SIEM en el período.")]
    return Section(
        number="4",
        title="Gestión Alarmas SIEM",
        subsections=[
            Subsection(number="4.1", title="Eventos SIEM", blocks=blocks_41),
            Subsection(number="4.2", title="Alarma Significativa", blocks=_significant(
                ctx["alerts"], f.SIEM, f"Durante el período {ctx['period_phrase']} se observó la siguiente alarma significativa:",
                "No se registraron alarmas de SIEM en el período.")),
        ],
    )


def _paired_rows(categories: list[tuple[str, int, str]], total_label: str, total: int) -> list[list[Cell]]:
    half = (len(categories) + 1) // 2
    left, right = categories[:half], categories[half:]
    rows = []
    for i in range(half):
        lc, ln, _ = left[i]
        row = [_c(lc), _c(ln, align="center")]
        if i < len(right):
            rc, rn, _ = right[i]
            row += [_c(rc), _c(rn, align="center")]
        else:
            row += [_c(""), _c("")]
        rows.append(row)
    rows.append([_c(""), _c(""), _c(total_label, fill=GRAY, bold=True, align="center"),
                 _c(total, fill=GRAY, bold=True, align="center")])
    return rows


def _network(ctx: dict) -> Section:
    red = f.effective(f.of_service(ctx["alerts"], f.RED))
    categories = f.categories_of(red)
    critical = f.highest_criticality(red)
    events_blocks: list = []
    if red:
        events_blocks = [
            ParagraphBlock(text=f"A continuación, se relacionan los eventos reportados durante el período "
                                f"{ctx['period_phrase']} sobre el antígeno de red:"),
            TableBlock(header_rows=[[_h("Eventos"), _h("Alarmas"), _h("Eventos"), _h("Alarmas")]],
                       rows=_paired_rows(categories, "TOTAL ALARMAS ANTÍGENO RED", len(red)),
                       widths=[2.2, 0.75, 2.6, 0.75], font_size=10),
        ]
        if critical:
            events_blocks += [
                MinorHeadingBlock(text="Mayor nivel criticidad"),
                TableBlock(header_rows=[[_h("Eventos"), _h("Riesgo"), _h("Alarmas")]],
                           rows=[[_c(c), _risk(r), _c(n, align="center")] for c, r, n in critical],
                           widths=[2.9, 2.0, 1.4]),
            ]
    else:
        events_blocks = [ParagraphBlock(text="No se registraron alarmas del antígeno de red en el período.")]
    return Section(
        number="5",
        title="Antígeno de Red",
        blocks=[
            ParagraphBlock(text=f"Durante el período {ctx['period_phrase']}, el antígeno de red reportó {len(red)} alarmas "
                                "efectivas para su gestión por el equipo CSOC."),
            _notice("incluir la vista del panel de análisis del antígeno de red"),
        ],
        subsections=[
            Subsection(number="5.1", title="Eventos Antígeno de Red", blocks=events_blocks),
            Subsection(number="5.2", title="Alarmas Significativas Antígeno de Red", blocks=_significant(
                ctx["alerts"], f.RED, f"Se relaciona a continuación una alarma significativa durante el período "
                                      f"{ctx['period_phrase']}:",
                "No se registraron alarmas del antígeno de red en el período.")),
        ],
    )


def _email(ctx: dict) -> Section:
    alerts = ctx["alerts"]
    email = f.effective(f.of_service(alerts, f.CORREO))
    inbound = f.top_inbound_recipients(alerts)
    leaks = f.top_leak_senders(alerts)
    inbound_blocks: list = [
        ParagraphBlock(text=f"A continuación, se relacionan los correos de {ctx['company']} con mayor tráfico de correos "
                            f"potencialmente maliciosos {ctx['range_phrase']}, según las alarmas del antígeno de correo:"),
        TableBlock(header_rows=[[_h("TOP CORREOS MAYOR TRÁFICO DE CORREOS MALICIOSOS"), _h("CANTIDAD RECIBIDOS")]],
                   rows=[[_c(e), _c(n, align="center")] for e, n in inbound], widths=[4.2, 2.0]),
    ] if inbound else [ParagraphBlock(text="No se registraron alarmas de correos maliciosos entrantes en el período.")]
    leak_blocks: list = [
        ParagraphBlock(text=f"A continuación, se relacionan los usuarios internos de {ctx['company']} que presentaron "
                            f"alarmas de correos salientes con posible fuga de información {ctx['range_phrase']}:"),
        TableBlock(header_rows=[[_h("TOP CORREOS SALIENTES – POSIBLE FUGA DE INFORMACIÓN"), _h("CANTIDAD")]],
                   rows=[[_c(e), _c(n, align="center")] for e, n in leaks], widths=[4.2, 2.0]),
    ] if leaks else [ParagraphBlock(text="No se registraron alarmas de posible fuga de información en el período.")]
    return Section(
        number="6",
        title="Antígeno de Correo",
        blocks=[
            ParagraphBlock(text=f"Durante el período {ctx['period_phrase']}, el antígeno de correo reportó {len(email)} "
                                "alarmas efectivas para su gestión por el equipo CSOC."),
            _notice("reportar el número de buzones integrados, el volumen de correos entrantes y salientes analizados "
                    "ni la vista del panel del antígeno de correo"),
        ],
        subsections=[
            Subsection(number="6.1", title="Top 10 Usuarios Con Mayor Tráfico De Correos Maliciosos Entrantes",
                       blocks=inbound_blocks),
            Subsection(number="6.2", title="Top 10 Correos Con Mayor Índice De Rareza Del 96% Al 100%",
                       blocks=[_notice("relacionar los correos por índice de rareza, ya que la fuente no entrega esa "
                                       "métrica")]),
            Subsection(number="6.3", title="Top 10 Usuarios De Posible Fuga De Información", blocks=leak_blocks),
            Subsection(number="6.4", title="Alarmas Significativas Antígeno Correo", blocks=_significant(
                alerts, f.CORREO, "Se relaciona a continuación la alarma significativa del antígeno de correo:",
                "No se registraron alarmas del antígeno de correo en el período.")),
        ],
    )


def _threat_intel(ctx: dict) -> Section:
    intel = f.effective(f.of_service(ctx["alerts"], f.INTEL))
    categories = f.categories_of(intel)
    return Section(
        number="7",
        title="Inteligencia de Amenazas",
        subsections=[
            Subsection(number="7.1", title="Monitoreo de Marca",
                       blocks=[_notice("reportar el monitoreo de marca y dominios")]),
            Subsection(number="7.2", title="Vulnerabilidades",
                       blocks=[_notice("reportar el estado de vulnerabilidades, remediaciones ni adversarios")]),
            Subsection(number="7.3", title="Alarmas Inteligencia De Amenazas", blocks=[
                ParagraphBlock(text=f"Durante el período {ctx['period_phrase']} se reportaron {len(intel)} eventos de "
                                    "inteligencia de amenazas:"),
                TableBlock(header_rows=[[_h("Eventos"), _h("Riesgo"), _h("Alarmas")]],
                           rows=[[_c(c), _risk(r), _c(n, align="center")] for c, n, r in categories],
                           widths=[2.9, 2.0, 1.4]),
            ] if intel else [ParagraphBlock(text="No se registraron alarmas de inteligencia de amenazas en el período.")]),
            Subsection(number="7.4", title="Alarmas Significativas Inteligencia De Amenazas", blocks=_significant(
                ctx["alerts"], f.INTEL, "Se relaciona a continuación la alarma significativa de inteligencia de amenazas:",
                "No se registraron alarmas de inteligencia de amenazas en el período.")),
        ],
    )


def _behaviour(ctx: dict) -> Section:
    top = ctx["facts"]["top_categories"][:10]
    if len(top) < 3:
        blocks = [_notice("construir el análisis de comportamiento (se requieren al menos tres categorías de alarmas)")]
    else:
        blocks = [
            ParagraphBlock(text=f"Durante el período {ctx['period_phrase']} se realizó un seguimiento a las categorías de "
                                "alarmas registradas, con el fin de identificar las más frecuentes. A continuación, se "
                                "detallan las categorías más relevantes del período evaluado:"),
            ChartBlock(chart="radar", title="Frecuencia por categoría", categories=[c for c, _ in top],
                       series=[ChartSeries(name="Frecuencia por categoría", values=[n for _, n in top], color="9DC3E6")],
                       height_inches=3.6),
        ]
    return Section(number="8", title="Análisis de Comportamiento", blocks=blocks)


def _ioc(ctx: dict) -> Section:
    alerts, start, end = ctx["alerts"], ctx["start"], ctx["end"]
    sources, targets = f.top_ips(alerts, "source_ips"), f.top_ips(alerts, "external_ips")

    def ip_table(rows: list[tuple[str, int]]) -> TableBlock:
        return TableBlock(header_rows=[[_h("IP"), _h("Ocurrencias")]],
                          rows=[[_c(ip), _c(n, align="center")] for ip, n in rows] or [[_c("Sin datos"), _c("-")]],
                          widths=[1.9, 1.1])

    days = f.daily_counts(alerts, start, end)
    return Section(
        number="9",
        title="Indicadores de Compromiso",
        blocks=[
            ParagraphBlock(text=f"Los indicadores técnicos presentados a continuación consolidan los principales orígenes y "
                                f"destinos de los eventos de seguridad registrados para {ctx['company']} durante el período "
                                f"{ctx['period_phrase']}, así como la evolución diaria de las alarmas."),
            SideBySideBlock(titles=("Top 5 de eventos IP origen.", "Top 5 de eventos IP destino."),
                            left=ip_table(sources), right=ip_table(targets)),
            MinorHeadingBlock(text="Gestión de alarmas por día"),
            ChartBlock(chart="line", title="Alarmas por día", categories=[d for d, _ in days],
                       series=[ChartSeries(name="Alarmas por día", values=[n for _, n in days], color="E06666")],
                       x_label="Fechas", y_label="Cantidad de alarmas", height_inches=2.8),
            MinorHeadingBlock(text="Análisis de IP's"),
            _notice("reportar la reputación de direcciones IP (reportes de proveedores de seguridad)"),
        ],
    )


def _highlights(ctx: dict) -> Section:
    facts, alerts = ctx["facts"], ctx["alerts"]
    hosts = f.disconnected_agents(alerts)
    items = [
        (f"Se registraron {facts['total_alarms']} alarmas, de las cuales {facts['effective_alarms']} fueron efectivas "
         f"y {facts['voided_alarms']} anuladas."),
        (f"{facts['answered']} alarmas cuentan con respuesta registrada y {facts['unanswered']} permanecen sin respuesta "
         "al corte del informe."),
        (f"Las alarmas de riesgo crítico y alto suman {facts['high_or_critical']} "
         f"({facts['high_or_critical_percent']}% de las alarmas efectivas)."),
    ]
    if facts["top_categories"]:
        category, count = facts["top_categories"][0]
        items.append(f"La categoría más frecuente fue {category} con {count} alarmas.")
    if hosts:
        items.append(f"Se reportaron {len(hosts)} servidores con agente desconectado; el detalle se encuentra en la "
                     "sección 3.3.")
    return Section(
        number="10",
        title="Actividades Destacadas",
        blocks=[
            ParagraphBlock(text=f"Durante las fechas de monitoreo {ctx['range_phrase']}, se realizó el análisis de monitoreo "
                                "y alertamiento de actividades detectadas. Se destacan las siguientes novedades registradas "
                                "en las fuentes de datos:"),
            BulletsBlock(items=items),
            _notice("reportar proyectos o actividades adicionales del período"),
        ],
    )


def build_context(collected: dict, start: date, end: date, company: str) -> dict:
    alerts = collected.get("alerts", [])
    history = collected.get("history_3mo") or f.monthly_history(alerts, f.last_three_months(end))
    facts = f.build_facts(alerts, history, start, end)
    whole_month = facts["period"] == f"{f.MONTHS[start.month - 1]} de {start.year}" and start.month == end.month
    return {
        "alerts": alerts,
        "history": history,
        "facts": facts,
        "company": company,
        "start": start,
        "end": end,
        "period_phrase": f"de {facts['period']}" if whole_month else facts["period"],
        "range_phrase": f"del {f.spanish_date(start)} al {f.spanish_date(end)}",
        "period_title": f"{f.MONTHS[end.month - 1].capitalize()} {end.year}" if whole_month else facts["period"],
        "month_name": f.MONTHS[end.month - 1].capitalize() if whole_month else "Período",
    }


def build_csoc_mensual_sections(collected: dict, narrative: ReportNarrative) -> list[Section]:
    """Chapters 3-10 of the client's "Informe de Gestión CSOC". Chapters 1 (objective), 2 (services)
    and 11 (recommendations) are assembled by specification.py around these."""
    company = (collected.get("company") or {}).get("name") or ""
    start = date.fromisoformat(collected["period"]["start"])
    end = date.fromisoformat(collected["period"]["end"])
    ctx = build_context(collected, start, end, company)
    return [_inventory(ctx), _siem(ctx), _network(ctx), _email(ctx), _threat_intel(ctx), _behaviour(ctx), _ioc(ctx),
            _highlights(ctx)]


register_template(DEFAULT_TEMPLATE_KEY, build_csoc_mensual_sections)
