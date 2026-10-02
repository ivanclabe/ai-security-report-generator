"""Normalizes the alarm rows delivered by the data source (the detailed-alarms
CSV export) into NormalizedSecurityAlert records.

This is the one place that knows about the messy source format: multi-value
IP/hostname fields, numeric-or-"ANULADO" severity, _x000D_ text artifacts,
inconsistent nulls. Everything downstream (tools, agent, report builder)
only ever sees the clean NormalizedSecurityAlert shape.

Input is a plain DataFrame (see csv_decoder.py for bytes -> DataFrame), so the
same normalization serves any future source that can produce those columns.
"""
import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.models.domain import (
    EscalationFlags,
    MitreTactic,
    NormalizedSecurityAlert,
    PersonRef,
    RiskLevel,
    risk_level_from_score,
)

_MULTI_VALUE_SPLIT = re.compile(r"[-\t\n]+")

# Unconditionally required columns, checked once up front -- a single clear
# diagnostic instead of one warning per row when the source renames or drops
# a column entirely.
_REQUIRED_COLUMNS = ("id", "cliente", "timestamp")
# At least one of these must be present to derive created_at.
_REQUIRED_ANY_OF = ("created_at", "fecha_de_creacion_alarma")


def load_mitre_catalog(path: Path) -> dict[str, MitreTactic]:
    data = json.loads(path.read_text())
    return {t["id"]: MitreTactic(**t) for t in data["tactics"]}


def _is_na(value) -> bool:
    if value is None:
        return True
    try:
        result = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return bool(result)


def _clean_text(value) -> str | None:
    if _is_na(value):
        return None
    text = str(value).replace("_x000D_", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text or None


def _split_multi_value(value) -> list[str]:
    text = _clean_text(value)
    if not text:
        return []
    parts = [p.strip() for p in _MULTI_VALUE_SPLIT.split(text)]
    return [p for p in parts if p]


def _to_bool_flag(value) -> bool:
    text = _clean_text(value)
    if not text:
        return False
    return text.strip().upper() in {"SI", "SÍ", "YES", "TRUE", "1"}


def _to_datetime(value) -> datetime | None:
    if _is_na(value):
        return None
    if isinstance(value, datetime):
        return value
    parsed = pd.to_datetime(value, errors="coerce", dayfirst=False)
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def _to_str_or_none(value) -> str | None:
    if _is_na(value):
        return None
    return str(value).strip() or None


def _parse_severity(raw) -> int | None:
    """Severity arrives as 80, 80.0 (float) or "80"/"80.0" (CSV text)."""
    try:
        return int(raw)
    except (TypeError, ValueError):
        pass
    try:
        return int(float(str(raw).strip().replace(",", ".")))
    except (TypeError, ValueError):
        return None


def _row_to_raw_record(row: pd.Series) -> dict:
    record = {}
    for key, value in row.items():
        if _is_na(value):
            record[key] = None
        elif isinstance(value, datetime):
            record[key] = value.isoformat()
        else:
            record[key] = value if isinstance(value, (str, int, float, bool)) else str(value)
    return record


class NormalizationResult:
    def __init__(self, alerts: list[NormalizedSecurityAlert], warnings: list[str]):
        self.alerts = alerts
        self.warnings = warnings


def _check_required_columns(df: pd.DataFrame, source_label: str) -> list[str]:
    """One aggregated diagnostic for missing columns, instead of a warning per
    row repeating the same cause for every row."""
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if not any(c in df.columns for c in _REQUIRED_ANY_OF):
        missing.append(f"one of {_REQUIRED_ANY_OF}")
    if not missing:
        return []
    return [f"'{source_label}': missing required column(s): {', '.join(missing)}"]


def normalize_alarm_rows(
    df: pd.DataFrame, mitre_catalog: dict[str, MitreTactic], source_label: str = "Alarmas"
) -> NormalizationResult:
    column_warnings = _check_required_columns(df, source_label)
    if column_warnings:
        # A missing column fails every row identically -- one diagnostic beats
        # N repeats of the same underlying cause.
        return NormalizationResult(alerts=[], warnings=column_warnings)

    if df.empty:
        return NormalizationResult(alerts=[], warnings=[f"'{source_label}' contains no data rows."])

    warnings: list[str] = []
    alerts: list[NormalizedSecurityAlert] = []
    seen_keys: set[tuple[str, str]] = set()

    for idx, row in df.iterrows():
        row_label = f"row {idx + 2}"  # +2: 1-indexed + header row

        raw_id = _to_str_or_none(row.get("id"))
        if raw_id is None:
            warnings.append(f"{row_label}: missing 'id', row skipped")
            continue

        alarm_number = _to_str_or_none(row.get("alarma_no")) or raw_id
        client = _to_str_or_none(row.get("cliente"))
        if client is None:
            warnings.append(f"{row_label} (id={raw_id}): missing 'cliente', row skipped")
            continue

        dedup_key = (client, alarm_number)
        if dedup_key in seen_keys:
            warnings.append(
                f"{row_label} (id={raw_id}): duplicate alarm_number '{alarm_number}' for client "
                f"'{client}', row skipped"
            )
            continue
        seen_keys.add(dedup_key)

        event_timestamp = _to_datetime(row.get("timestamp"))
        created_at = _to_datetime(row.get("created_at")) or _to_datetime(row.get("fecha_de_creacion_alarma"))
        reported_at = _to_datetime(row.get("hora_reporte")) or created_at
        if event_timestamp is None or created_at is None:
            warnings.append(f"{row_label} (id={raw_id}): missing required timestamp, row skipped")
            continue

        raw_severity = row.get("severity")
        severity_score: int | None
        is_voided = False
        if isinstance(raw_severity, str) and raw_severity.strip().upper() == "ANULADO":
            severity_score = None
            is_voided = True
        else:
            severity_score = _parse_severity(raw_severity)
            if severity_score is None:
                warnings.append(f"{row_label} (id={raw_id}): unparseable severity '{raw_severity}', treated as unknown")

        computed_risk = risk_level_from_score(severity_score) if not is_voided else RiskLevel.ANULADO
        given_riesgo = _clean_text(row.get("Riesgo"))
        risk_level = computed_risk
        if given_riesgo:
            try:
                risk_level = RiskLevel(given_riesgo.strip().capitalize())
            except ValueError:
                risk_level = computed_risk
            else:
                if risk_level != computed_risk and not is_voided:
                    warnings.append(
                        f"{row_label} (id={raw_id}): source Riesgo='{given_riesgo}' does not match "
                        f"severity-derived '{computed_risk.value}' (severity={severity_score}); using source value"
                    )

        mitre_id = _to_str_or_none(row.get("mitre"))
        mitre_name = None
        if mitre_id and mitre_id.upper() != "ANULADO":
            tactic = mitre_catalog.get(mitre_id)
            if tactic:
                mitre_name = tactic.name_es
            else:
                mitre_name = _clean_text(row.get("descripcion mitre"))
                warnings.append(f"{row_label} (id={raw_id}): mitre id '{mitre_id}' not in catalog, using source label")
        elif mitre_id and mitre_id.upper() == "ANULADO":
            mitre_id = None

        response = _clean_text(row.get("respuesta"))
        responded_at = _to_datetime(row.get("fecha_respuesta"))

        reported_by = PersonRef(
            name=_to_str_or_none(row.get("quien_reporta")),
            role=_to_str_or_none(row.get("cargo_reporta")),
            contact=_to_str_or_none(row.get("contacto_reporta")),
        )
        authorized_by = PersonRef(
            name=_to_str_or_none(row.get("autorizado_por")),
            role=_to_str_or_none(row.get("cargo_autoriza")),
            contact=None,
        )

        category = _clean_text(row.get("category")) or "Sin categoría"
        description = _clean_text(row.get("description")) or ""

        alert_type = _clean_text(row.get("tipo"))
        if alert_type is None:
            warnings.append(f"{row_label} (id={raw_id}): missing 'tipo', defaulting to 'Desconocido'")
            alert_type = "Desconocido"

        alerts.append(
            NormalizedSecurityAlert(
                id=raw_id,
                alarm_number=alarm_number,
                original_id=_to_str_or_none(row.get("original_id")),
                client=client,
                alert_type=alert_type,
                category=category,
                severity_score=severity_score,
                risk_level=risk_level,
                is_voided=is_voided,
                event_timestamp=event_timestamp,
                created_at=created_at,
                reported_at=reported_at or created_at,
                source_ips=_split_multi_value(row.get("sourceIP")),
                external_ips=_split_multi_value(row.get("externalIP")),
                hostnames=_split_multi_value(row.get("hostname")),
                description=description,
                url=_to_str_or_none(row.get("url")),
                mitre_tactic_id=mitre_id,
                mitre_tactic_name=mitre_name,
                reported_by=reported_by if reported_by.name else None,
                authorized_by=authorized_by if authorized_by.name else None,
                escalation=EscalationFlags(
                    called=_to_bool_flag(row.get("llamado")),
                    glpi_ticket=_to_bool_flag(row.get("glpi")),
                    sharepoint_doc=_to_bool_flag(row.get("sharepoint")),
                ),
                recommendations=_clean_text(row.get("recomendaciones")),
                response=response,
                responded_at=responded_at,
                status="resolved" if response else "open",
                raw_record=_row_to_raw_record(row),
            )
        )

    return NormalizationResult(alerts=alerts, warnings=warnings)
