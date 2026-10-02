"""Facts of the CSOC management report, computed deterministically from the alarms.

Every figure, table row and chart value of the report comes from here (or from
the alarms directly) -- never from the LLM. The functions take the alarms as
the JSON dicts collected by app/services/report/collection.py
(NormalizedSecurityAlert.model_dump(mode="json")).

`allowed_numbers()` lists every number these facts can justify; the
recommendations written by the LLM are checked against it (validation.py) so a
figure that the data does not support never reaches the document.
"""
import ipaddress
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from app.services.report.narrative import (
    DISCONNECTED_CATEGORY,
    EMAIL_TYPE,
    NETWORK_TYPE,
    SIEM_TYPE,
    THREAT_INTEL_TYPES,
)

MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
          "noviembre", "diciembre"]
MONTHS_SHORT = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

SIEM = "SIEM"
RED = "Antígeno de Red"
CORREO = "Antígeno de Correo"
INTEL = "Inteligencia de Amenazas"
ZABBIX = "Zabbix"
ANULADAS = "Anuladas"
SERVICE_ORDER = [SIEM, RED, CORREO, INTEL, ZABBIX]

_SERVICE_OF_TYPE = {
    SIEM_TYPE.upper(): SIEM,
    NETWORK_TYPE.upper(): RED,
    EMAIL_TYPE.upper(): CORREO,
    **{t.upper(): INTEL for t in THREAT_INTEL_TYPES},
    "ZABBIX": ZABBIX,
    "ANULADO": ANULADAS,
}

RISK_ORDER = ["Critico", "Alto", "Medio", "Bajo"]
RISK_LABEL = {"Critico": "Crítico", "Alto": "Alto", "Medio": "Medio", "Bajo": "Bajo"}

NO_EVIDENCE = "No se encontró evidencia suficiente en las fuentes de datos disponibles para completar esta sección."


# ---- basics -------------------------------------------------------------------------------------


def service_of(alert: dict) -> str:
    alert_type = (alert.get("alert_type") or "").strip()
    if alert.get("is_voided"):
        return ANULADAS
    return _SERVICE_OF_TYPE.get(alert_type.upper(), alert_type.title() or "Sin tipo")


def is_effective(alert: dict) -> bool:
    return service_of(alert) != ANULADAS


def effective(alerts: list[dict]) -> list[dict]:
    return [a for a in alerts if is_effective(a)]


def _when(alert: dict) -> datetime:
    """The alarm's creation time -- the source filters its export by it."""
    value = alert.get("created_at") or alert.get("event_timestamp")
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def has_response(alert: dict) -> bool:
    return bool((alert.get("response") or "").strip())


def ordered_services(present: set[str]) -> list[str]:
    known = [s for s in SERVICE_ORDER if s in present]
    others = sorted(s for s in present if s not in SERVICE_ORDER and s != ANULADAS)
    return known + others


def month_key(d: date | datetime) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def month_label(key: str, *, short: bool = True) -> str:
    _year, month = key.split("-")
    names = MONTHS_SHORT if short else [m.capitalize() for m in MONTHS]
    return names[int(month) - 1]


def last_three_months(end: date) -> list[str]:
    keys = []
    year, month = end.year, end.month
    for _ in range(3):
        keys.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return list(reversed(keys))


def spanish_date(d: date, *, zero_pad: bool = True) -> str:
    day = f"{d.day:02d}" if zero_pad else str(d.day)
    return f"{day} de {MONTHS[d.month - 1]} de {d.year}"


def period_label(start: date, end: date) -> str:
    """'julio de 2026' for a whole calendar month, else 'del 01 de julio de 2026 al 15 de julio de 2026'."""
    next_day = end + timedelta(days=1)
    if start.day == 1 and next_day.day == 1 and start.month == end.month and start.year == end.year:
        return f"{MONTHS[start.month - 1]} de {start.year}"
    return f"del {spanish_date(start)} al {spanish_date(end)}"


def pct(part: int, total: int) -> int:
    return round(part * 100 / total) if total else 0


def trend_arrow(previous: int, current: int) -> str:
    return "↑" if current > previous else "↓" if current < previous else "="


def compress_alarm_numbers(numbers: list[str]) -> str:
    """['ALARMA TGS TPS 3636', 'ALARMA TGS TPS 3616'] -> 'ALARMA TGS TPS 3636, 3616'."""
    if not numbers:
        return ""
    split = [re.match(r"^(.*?)(\d+)\s*$", n) for n in numbers]
    if all(split) and len({m.group(1) for m in split}) == 1:
        return split[0].group(1) + ", ".join(m.group(2) for m in split)
    return ", ".join(numbers)


def _split(values: list[str] | None) -> list[str]:
    """Multi-valued fields sometimes arrive as one string ("SV1, SV2" / "a@x.com; b@y.com")."""
    out: list[str] = []
    for value in values or []:
        out.extend(part.strip() for part in re.split(r"[,;\s]+", str(value)) if part.strip())
    return out


def _alarm_sort_key(number: str) -> tuple:
    match = re.search(r"(\d+)\s*$", number)
    return (int(match.group(1)) if match else -1, number)


# ---- section facts -----------------------------------------------------------------------------------


def service_counts(alerts: list[dict]) -> dict[str, int]:
    return dict(Counter(service_of(a) for a in alerts))


def monthly_history(alerts: list[dict], month_keys: list[str]) -> dict:
    """Per month: alarms per service, voided, effective total, and risk distribution.

    `records` is how many alarms the source returned for that month; a month with
    zero records is reported as "N/D" (no data) rather than as zero alarms.
    """
    by_month: dict[str, list[dict]] = defaultdict(list)
    for alert in alerts:
        key = month_key(_when(alert))
        if key in month_keys:
            by_month[key].append(alert)
    months = []
    for key in month_keys:
        items = by_month.get(key, [])
        eff = effective(items)
        months.append({
            "month": key,
            "records": len(items),
            "services": service_counts(items),
            "voided": len(items) - len(eff),
            "effective": len(eff),
            "risk": {r: sum(1 for a in eff if a.get("risk_level") == r) for r in RISK_ORDER},
        })
    return {"months": months}


def has_records(month: dict) -> bool:
    """Whether the source returned any alarm for a `monthly_history` month (older payloads lack the field)."""
    return month.get("records", 1) > 0


def response_by_service(alerts: list[dict]) -> list[dict]:
    rows = []
    by_service: dict[str, list[dict]] = defaultdict(list)
    for alert in alerts:
        by_service[service_of(alert)].append(alert)
    for service in [*ordered_services(set(by_service)), ANULADAS]:
        items = by_service.get(service)
        if not items:
            continue
        answered = sum(1 for a in items if has_response(a))
        rows.append({"service": service, "answered": answered, "unanswered": len(items) - answered})
    return rows


def risk_distribution(alerts: list[dict]) -> dict[str, int]:
    eff = effective(alerts)
    return {r: sum(1 for a in eff if a.get("risk_level") == r) for r in RISK_ORDER}


def dominant_risk(alerts: list[dict]) -> str:
    counts = Counter(a.get("risk_level") for a in alerts if a.get("risk_level") in RISK_ORDER)
    if not counts:
        return "-"
    top = max(counts.values())
    # ties resolve to the more severe level
    return next(r for r in RISK_ORDER if counts.get(r) == top)


def categories_of(alerts: list[dict]) -> list[tuple[str, int, str]]:
    """[(category, count, dominant risk)] most frequent first."""
    by_category: dict[str, list[dict]] = defaultdict(list)
    for alert in alerts:
        by_category[alert.get("category") or "Sin categoría"].append(alert)
    return sorted(
        ((c, len(items), dominant_risk(items)) for c, items in by_category.items()),
        key=lambda row: (-row[1], row[0]),
    )


def highest_criticality(alerts: list[dict], limit: int = 8) -> list[tuple[str, str, int]]:
    """[(category, risk, count)] for Crítico/Alto/Medio alarms, most severe first."""
    counter = Counter(
        (a.get("category") or "Sin categoría", a.get("risk_level"))
        for a in alerts
        if a.get("risk_level") in ("Critico", "Alto", "Medio")
    )
    rows = sorted(counter.items(), key=lambda kv: (RISK_ORDER.index(kv[0][1]), -kv[1], kv[0][0]))
    return [(category, risk, count) for (category, risk), count in rows[:limit]]


def of_service(alerts: list[dict], service: str) -> list[dict]:
    return [a for a in alerts if service_of(a) == service]


def significant_alert(alerts: list[dict]) -> dict | None:
    """The alarm with the highest severity score (most recent on ties)."""
    candidates = [a for a in alerts if is_effective(a)]
    if not candidates:
        return None
    return max(candidates, key=lambda a: (a.get("severity_score") or 0, _when(a)))


def disconnected_agents(alerts: list[dict]) -> list[dict]:
    """One entry per host reported with a disconnected agent: IP, last alarm date, alarms."""
    hosts: dict[str, dict] = {}
    for alert in alerts:
        if (alert.get("category") or "").strip().lower() != DISCONNECTED_CATEGORY.lower() or not is_effective(alert):
            continue
        names = _split(alert.get("hostnames"))
        ips = _split(alert.get("source_ips"))
        for i, name in enumerate(names):
            ip = ips[i] if len(ips) == len(names) else "-"
            entry = hosts.setdefault(name, {"host": name, "ip": ip, "last": _when(alert), "alarms": set()})
            if entry["ip"] == "-" and ip != "-":
                entry["ip"] = ip
            entry["last"] = max(entry["last"], _when(alert))
            entry["alarms"].add(alert["alarm_number"])
    return [
        {**h, "alarms": sorted(h["alarms"], key=_alarm_sort_key, reverse=True)}
        for h in sorted(hosts.values(), key=lambda h: (-h["last"].timestamp(), h["host"]))
    ]


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value.strip())
    except ValueError:
        return False
    return True


def top_ips(alerts: list[dict], field: str, limit: int = 5) -> list[tuple[str, int]]:
    counter = Counter(ip for a in effective(alerts) for ip in _split(a.get(field)) if _is_ip(ip))
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]


def daily_counts(alerts: list[dict], start: date, end: date) -> list[tuple[str, int]]:
    counter = Counter(_when(a).date() for a in effective(alerts))
    days, current = [], start
    while current <= end:
        days.append((current.isoformat(), counter.get(current, 0)))
        current += timedelta(days=1)
    return days


def _emails(values: list[str]) -> list[str]:
    return [v.lower() for v in _split(values) if "@" in v]


def is_exfiltration(alert: dict) -> bool:
    return "exfiltraci" in (alert.get("category") or "").lower()


def top_inbound_recipients(alerts: list[dict], limit: int = 10) -> list[tuple[str, int]]:
    counter = Counter(
        email for a in of_service(alerts, CORREO) if not is_exfiltration(a) for email in _emails(a.get("external_ips"))
    )
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]


def top_leak_senders(alerts: list[dict], limit: int = 10) -> list[tuple[str, int]]:
    counter = Counter(
        email for a in of_service(alerts, CORREO) if is_exfiltration(a) for email in _emails(a.get("source_ips"))
    )
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]


# ---- everything the report states --------------------------------------------------------------------


def build_facts(alerts: list[dict], history: dict | None, start: date, end: date) -> dict:
    eff = effective(alerts)
    counts = service_counts(alerts)
    responses = response_by_service(alerts)
    answered = sum(r["answered"] for r in responses)
    risk = risk_distribution(alerts)
    high_critical = risk["Critico"] + risk["Alto"]
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "period": period_label(start, end),
        "total_alarms": len(alerts),
        "effective_alarms": len(eff),
        "voided_alarms": len(alerts) - len(eff),
        "alarms_by_service": counts,
        "answered": answered,
        "unanswered": len(alerts) - answered,
        "risk_distribution": risk,
        "risk_percent": {r: pct(n, len(eff)) for r, n in risk.items()},
        "high_or_critical": high_critical,
        "high_or_critical_percent": pct(high_critical, len(eff)),
        "top_categories": [(c, n) for c, n, _ in categories_of(eff)[:10]],
        "disconnected_hosts": len(disconnected_agents(alerts)),
        "monthly_effective": [(m["month"], m["effective"]) for m in (history or {}).get("months", []) if has_records(m)],
    }


def allowed_numbers(facts: dict, alerts: list[dict]) -> set[str]:
    """Every number the report can justify, as text: counts, percentages, dates and alarm numbers."""
    numbers: set[int] = set()

    def walk(value):
        if isinstance(value, bool):
            return
        if isinstance(value, (int, float)):
            numbers.add(round(value))
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            for match in re.findall(r"\d+", value):
                numbers.add(int(match))

    walk(facts)
    for alert in alerts:
        walk(alert.get("alarm_number") or "")
        if alert.get("severity_score") is not None:
            numbers.add(int(alert["severity_score"]))
    numbers.update(range(32))  # day numbers and small ordinals ("los 3 meses", "top 5", "10")
    numbers.update({100})
    return {str(n) for n in numbers}
