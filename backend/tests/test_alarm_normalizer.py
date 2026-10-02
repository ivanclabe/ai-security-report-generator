import pandas as pd

from app.ingestion.csv_decoder import decode_alarms_csv
from app.ingestion.normalizer import load_mitre_catalog, normalize_alarm_rows
from tests.conftest import (
    ALARMS_EMPTY_EXPORT_PATH,
    ALARMS_EXPECTED_RISK_PATH,
    ALARMS_FIXTURE_PATH,
    MITRE_CATALOG_PATH,
)


def _ingest():
    """The shipped CSV fixture (169 alarms of THOMAS TGS-TPS, July 2026), decoded exactly
    as the acquisition layer decodes a response from the source."""
    catalog = load_mitre_catalog(MITRE_CATALOG_PATH)
    return normalize_alarm_rows(decode_alarms_csv(ALARMS_FIXTURE_PATH.read_bytes()), catalog)


def _minimal_row(**overrides) -> dict:
    row = {
        "id": "1",
        "cliente": "ACME",
        "alarma_no": "A-1",
        "tipo": "NG SIEM FALCON",
        "category": "Test",
        "description": "desc",
        "timestamp": "2026-01-01T00:00:00",
        "created_at": "2026-01-01T00:00:00",
        "severity": 80,
    }
    row.update(overrides)
    return row


def test_ingests_all_rows_with_no_warnings():
    result = _ingest()
    assert len(result.alerts) == 169
    assert result.warnings == []


def test_risk_level_matches_the_clients_own_labels_for_every_row():
    # The live export no longer carries a 'Riesgo' column, so the level is always
    # computed from severity. This pins that computation to the labels the client's
    # previous export assigned to these same 169 alarms (expected file next to the
    # fixture) -- if the thresholds change, this shows exactly which alarms move.
    import json

    expected = json.loads(ALARMS_EXPECTED_RISK_PATH.read_text(encoding="utf-8"))["riesgo_por_alarma"]
    result = _ingest()
    mismatches = {
        a.alarm_number: (expected[a.alarm_number], a.risk_level.value)
        for a in result.alerts
        if not a.is_voided and expected[a.alarm_number] != a.risk_level.value
    }
    assert mismatches == {}


def test_the_live_export_has_no_riesgo_or_mitre_description_columns_and_still_normalizes():
    df = decode_alarms_csv(ALARMS_FIXTURE_PATH.read_bytes())
    assert "Riesgo" not in df.columns and "descripcion mitre" not in df.columns
    result = normalize_alarm_rows(df, load_mitre_catalog(MITRE_CATALOG_PATH))
    assert len(result.alerts) == 169
    assert all(a.risk_level.value for a in result.alerts)


def test_the_real_header_only_export_is_an_empty_result_with_one_explanation():
    df = decode_alarms_csv(ALARMS_EMPTY_EXPORT_PATH.read_bytes())
    assert len(df.columns) == 28 and df.empty
    result = normalize_alarm_rows(df, {})
    assert result.alerts == [] and len(result.warnings) == 1 and "no data rows" in result.warnings[0]


def test_voided_alarms_have_no_severity_score():
    result = _ingest()
    voided = [a for a in result.alerts if a.is_voided]
    assert len(voided) == 3
    for a in voided:
        assert a.severity_score is None
        assert a.risk_level.value == "Anulado"


def test_multi_value_hostname_and_ip_fields_are_split():
    result = _ingest()
    multi_host = [a for a in result.alerts if len(a.hostnames) > 1]
    assert len(multi_host) > 0
    for a in multi_host:
        assert all(h.strip() == h and h for h in a.hostnames)


def test_description_has_no_carriage_return_artifacts():
    result = _ingest()
    for a in result.alerts:
        assert "_x000D_" not in a.description
        if a.response:
            assert "_x000D_" not in a.response


def test_mitre_tactic_resolved_against_static_catalog():
    result = _ingest()
    disconnection_alerts = [a for a in result.alerts if a.mitre_tactic_id == "CUST01"]
    assert len(disconnection_alerts) > 0
    assert all(a.mitre_tactic_name == "Disconnection" for a in disconnection_alerts)

    official = [a for a in result.alerts if a.mitre_tactic_id == "TA0011"]
    assert len(official) > 0
    assert all(a.mitre_tactic_name == "Comando y control" for a in official)


def test_status_derived_from_response_presence():
    result = _ingest()
    unresolved = [a for a in result.alerts if a.status == "open"]
    assert len(unresolved) == 19
    for a in unresolved:
        assert a.response is None
        assert a.responded_at is None
    resolved = [a for a in result.alerts if a.status == "resolved"]
    for a in resolved:
        assert a.response is not None


def test_escalation_flags_parsed_as_booleans():
    result = _ingest()
    called = [a for a in result.alerts if a.escalation.called]
    assert len(called) == 1


def test_missing_optional_fields_become_none_not_placeholder_strings():
    result = _ingest()
    missing_original_id = [a for a in result.alerts if a.original_id is None]
    assert len(missing_original_id) == 24


def test_missing_required_column_yields_one_aggregated_warning_not_one_per_row():
    df = pd.DataFrame([_minimal_row(), _minimal_row(id="2")]).drop(columns=["cliente"])
    result = normalize_alarm_rows(df, {})
    assert result.alerts == []
    assert len(result.warnings) == 1
    assert "cliente" in result.warnings[0]


def test_empty_sheet_yields_explicit_warning():
    df = pd.DataFrame(columns=["id", "cliente", "timestamp", "created_at"])
    result = normalize_alarm_rows(df, {})
    assert result.alerts == []
    assert len(result.warnings) == 1
    assert "no data rows" in result.warnings[0]


def test_duplicate_alarm_number_for_same_client_is_skipped():
    df = pd.DataFrame([_minimal_row(), _minimal_row(id="2")])  # same cliente + alarma_no
    result = normalize_alarm_rows(df, {})
    assert len(result.alerts) == 1
    assert any("duplicate" in w for w in result.warnings)


def test_same_alarm_number_for_different_clients_is_not_a_duplicate():
    df = pd.DataFrame([_minimal_row(), _minimal_row(id="2", cliente="OTHER CO")])
    result = normalize_alarm_rows(df, {})
    assert len(result.alerts) == 2
    assert result.warnings == []


def test_missing_tipo_defaults_and_warns():
    df = pd.DataFrame([_minimal_row(tipo=None)])
    result = normalize_alarm_rows(df, {})
    assert len(result.alerts) == 1
    assert result.alerts[0].alert_type == "Desconocido"
    assert any("tipo" in w for w in result.warnings)


def test_severity_is_parsed_from_csv_text_including_decimals():
    df = pd.DataFrame(
        [
            _minimal_row(severity="80"),
            _minimal_row(id="2", alarma_no="A-2", severity="85.0"),
            _minimal_row(id="3", alarma_no="A-3", severity="90,5"),
            _minimal_row(id="4", alarma_no="A-4", severity="ANULADO"),
            _minimal_row(id="5", alarma_no="A-5", severity="n/a"),
        ]
    )
    result = normalize_alarm_rows(df, {})
    by_number = {a.alarm_number: a for a in result.alerts}
    assert [by_number[n].severity_score for n in ("A-1", "A-2", "A-3")] == [80, 85, 90]
    assert by_number["A-4"].is_voided and by_number["A-4"].severity_score is None
    assert by_number["A-5"].severity_score is None
    assert sum("unparseable severity" in w for w in result.warnings) == 1
