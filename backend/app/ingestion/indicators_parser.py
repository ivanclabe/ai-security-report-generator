"""Indicators page of the source (indicadores.php) -> SourceIndicators.

The page is an HTML dashboard, not an API, but it carries all its numbers in a
machine-readable way, which is what this reads (never the rendered charts):

* the executive summary   <div class="resumen-ejecutivo"> ... <strong>226</strong> alarmas entre
                          <strong>2026-08-01</strong> y <strong>2026-09-04</strong> ... origen: <strong>IP</strong>
* "top" tables            <table class="top-table"> under an <h3> (risk by severity, top IPs,
                          hostnames, descriptions)
* inline script literals  const DATA = [...]          (one object per alarm, reduced fields)
                          const porDiaRaw = {...}     (alarms per day)
                          const categoriasData = {...} (top categories)
* the client selector     <select name="cliente"> (selected client + every client the source knows)

Tables are found by their heading's words (accent-insensitive), script values by
their variable name, so cosmetic changes to the page do not break parsing; a page
with none of these markers (a login page, an error page) is rejected.
"""
import json
import re
import unicodedata
from collections import Counter
from datetime import date, datetime

from lxml import etree
from lxml import html as lxml_html

from app.ingestion.encoding import decode_source_text
from app.ingestion.errors import SourceFormatError
from app.models.domain import (
    IndicatorCount,
    IndicatorRecord,
    RiskShare,
    SourceIndicators,
)

_SUMMARY = re.compile(
    r"identificaron\s+(?P<total>\d+)\s+alarmas\s+entre\s+(?P<start>\d{4}-\d{2}-\d{2})\s+y\s+(?P<end>\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
_PRINCIPAL_IP = re.compile(r"principal\s+origen:\s*(?P<ip>[^\s<]+?)\.?\s*$", re.IGNORECASE | re.MULTILINE)
_RISK_LABEL = re.compile(r"^(?P<level>[^(]+?)\s*(?:\((?P<range>[^)]*)\))?$")
_JS_ASSIGNMENT = r"(?:const|let|var)\s+{name}\s*="


def _plain(value: str) -> str:
    text = "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))
    return " ".join(text.lower().split())


def _text(element) -> str:
    return " ".join(element.text_content().split())


def _class_xpath(cls: str) -> str:
    return f"//*[contains(concat(' ', normalize-space(@class), ' '), ' {cls} ')]"


def _js_literal(scripts: str, name: str):
    """Value of `const <name> = <JSON literal>;` in the page's inline scripts, or None."""
    match = re.search(_JS_ASSIGNMENT.format(name=re.escape(name)), scripts)
    if not match:
        return None
    start = match.end()
    while start < len(scripts) and scripts[start].isspace():
        start += 1
    try:
        value, _ = json.JSONDecoder().raw_decode(scripts, start)
    except json.JSONDecodeError:
        return None
    return value


def _to_int(value) -> int | None:
    try:
        return int(float(str(value).strip().replace("%", "").replace(",", ".")))
    except (TypeError, ValueError):
        return None


def _to_datetime(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).strip())
    except ValueError:
        return None


def _to_date(value) -> date | None:
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None


def _counts(mapping) -> list[IndicatorCount]:
    if not isinstance(mapping, dict):
        return []
    items = [IndicatorCount(label=str(k), count=c) for k, v in mapping.items() if (c := _to_int(v)) is not None]
    return sorted(items, key=lambda i: i.count, reverse=True)


def _record(raw: dict) -> IndicatorRecord:
    def text(key: str) -> str | None:
        value = raw.get(key)
        value = str(value).strip() if value is not None else ""
        return value or None

    return IndicatorRecord(
        alert_type=text("tipo") or "Desconocido",
        timestamp=_to_datetime(raw.get("timestamp")),
        source_ip=text("sourceIP"),
        external_ip=text("externalIP"),
        hostname=text("hostname"),
        description=(text("description") or "").replace("\r\n", "\n"),
        reported_by=text("quien_reporta"),
        created_at=_to_datetime(raw.get("fecha_de_creacion_alarma")),
        severity_score=_to_int(raw.get("severity")),
    )


def _tables_by_heading(doc) -> dict[str, list[list[str]]]:
    """{plain heading text: body rows} for every table under a dashboard heading."""
    tables: dict[str, list[list[str]]] = {}
    for table in doc.xpath("//table"):
        heading = table.xpath("preceding::h3[1]")
        if not heading:
            continue
        rows = []
        for tr in table.xpath(".//tbody/tr") or table.xpath(".//tr")[1:]:
            cells = []
            for td in tr.xpath("./td"):
                # long descriptions are truncated with CSS; the full text is in title=
                cells.append(" ".join((td.get("title") or td.text_content()).split()))
            if cells:
                rows.append(cells)
        tables[_plain(_text(heading[0]))] = rows
    return tables


def _table(tables: dict[str, list[list[str]]], *words: str) -> list[list[str]] | None:
    for heading, rows in tables.items():
        if all(w in heading for w in words):
            return rows
    return None


def _top_counts(rows: list[list[str]] | None) -> list[IndicatorCount]:
    result = []
    for row in rows or []:
        if len(row) >= 2 and (count := _to_int(row[-1])) is not None:
            result.append(IndicatorCount(label=row[0], count=count))
    return result


def _risk_shares(rows: list[list[str]] | None) -> list[RiskShare]:
    shares = []
    for row in rows or []:
        if len(row) < 2:
            continue
        try:
            percent = float(row[1].replace("%", "").replace(",", ".").strip())
        except ValueError:
            continue
        label = _RISK_LABEL.match(row[0].strip())
        shares.append(
            RiskShare(
                level=(label.group("level") if label else row[0]).strip(),
                range_label=(label.group("range") or None) if label else None,
                percent=percent,
            )
        )
    return shares


def parse_indicators_page(content: bytes) -> SourceIndicators:
    page = decode_source_text(content)
    try:
        doc = lxml_html.fromstring(page)
    except (ValueError, etree.ParserError) as exc:
        raise SourceFormatError("La página de indicadores está vacía o no es HTML.") from exc

    if doc.xpath("//input[translate(@type, 'PASSWORD', 'password')='password']"):
        raise SourceFormatError(
            "La fuente devolvió una página de inicio de sesión en lugar de los indicadores (sesión no iniciada)."
        )

    scripts = "\n".join(s.text or "" for s in doc.xpath("//script[not(@src)]"))
    summary_nodes = doc.xpath(_class_xpath("resumen-ejecutivo"))
    no_data = bool(doc.xpath(_class_xpath("no-data")))
    raw_records = _js_literal(scripts, "DATA")
    if not summary_nodes and not no_data and raw_records is None:
        raise SourceFormatError(
            "La respuesta de indicadores no tiene el formato esperado (no hay resumen ejecutivo ni datos): "
            "puede ser una página de error o la ruta SOURCE_INDICATORS_PATH no es la correcta."
        )

    warnings: list[str] = []
    records = [_record(r) for r in raw_records if isinstance(r, dict)] if isinstance(raw_records, list) else []

    total = start = end = principal_ip = None
    if summary_nodes:
        summary_text = " ".join(summary_nodes[0].text_content().split())
        if match := _SUMMARY.search(summary_text):
            total = int(match.group("total"))
            start, end = _to_date(match.group("start")), _to_date(match.group("end"))
        if match := _PRINCIPAL_IP.search(summary_text):
            principal_ip = match.group("ip")
    if total is None:
        total = 0 if (no_data and not records) else len(records)
        if summary_nodes:
            warnings.append("No se pudo leer el total del resumen ejecutivo; se usó la cantidad de registros listados.")
    if records and total != len(records):
        warnings.append(f"El resumen indica {total} alarmas pero la página lista {len(records)} registros.")

    selected = doc.xpath("//select[@name='cliente']//option[@selected]")
    client = None
    if selected:
        client = (selected[0].get("value") or "").strip() or None
    seen: list[str] = []
    for option in doc.xpath("//select[@name='cliente']//option"):
        value = (option.get("value") or "").strip()
        if value and value not in seen:
            seen.append(value)

    if start is None:
        start = _to_date((doc.xpath("//input[@name='fecha_inicio']/@value") or [""])[0])
    if end is None:
        end = _to_date((doc.xpath("//input[@name='fecha_fin']/@value") or [""])[0])

    tables = _tables_by_heading(doc)
    by_type = Counter(r.alert_type for r in records)
    return SourceIndicators(
        client=client,
        start_date=start,
        end_date=end,
        total_alarms=total,
        principal_source_ip=principal_ip,
        risk_distribution=_risk_shares(_table(tables, "riesgo")),
        alarms_by_type=[IndicatorCount(label=k, count=v) for k, v in by_type.most_common()],
        alarms_by_day=sorted(_counts(_js_literal(scripts, "porDiaRaw")), key=lambda i: i.label),
        top_categories=_counts(_js_literal(scripts, "categoriasData")),
        top_source_ips=_top_counts(_table(tables, "ip", "origen")),
        top_destination_ips=_top_counts(_table(tables, "ip", "destino")),
        top_hostnames=_top_counts(_table(tables, "hostname")),
        top_descriptions=_top_counts(_table(tables, "descripcion")),
        records=records,
        available_clients=seen,
        warnings=warnings,
    )
