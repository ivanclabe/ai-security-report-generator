from app.schemas.report_spec import (
    DocumentControl,
    EvidenceRef,
    KeyFinding,
    ReportPeriod,
    ReportSpecification,
    Section,
    SignificantAlert,
)


def _spec(*, sections: list[Section] | None = None, recommendations: list[KeyFinding] | None = None) -> ReportSpecification:
    return ReportSpecification(
        document_control=DocumentControl(titulo="t", fecha_version="2026-08-01"),
        company="THOMAS TGS-TPS",
        period=ReportPeriod(start="2026-07-01", end="2026-07-31"),
        objective="o",
        sections=sections if sections is not None else [Section(number="3", title="Inventario")],
        recommendations=recommendations if recommendations is not None else [KeyFinding(statement="r")],
    )


def test_empty_sections_rejected():
    errors = _spec(sections=[]).validate_business_rules()
    assert any("at least one section" in e for e in errors)


def test_empty_recommendations_rejected():
    errors = _spec(recommendations=[]).validate_business_rules()
    assert any("at least one recommendation" in e for e in errors)


def test_valid_spec_has_no_business_errors():
    assert _spec().validate_business_rules() == []


def test_validate_evidence_flags_unknown_alarm_in_recommendation():
    spec = _spec(recommendations=[KeyFinding(statement="Made up trend", evidence=EvidenceRef(source_alarm_numbers=["FAKE-999"]))])
    errors = spec.validate_evidence(known_alarm_numbers={"ALARMA TGS TPS 3636"})
    assert any("FAKE-999" in e for e in errors)


def test_validate_evidence_flags_unknown_alarm_in_significant_alert():
    section = Section(
        number="4",
        title="SIEM",
        significant_alerts=[SignificantAlert(alarm_number="FAKE-1", heading="FAKE-1", description="x")],
    )
    spec = _spec(sections=[section])
    errors = spec.validate_evidence(known_alarm_numbers={"ALARMA TGS TPS 3636"})
    assert any("FAKE-1" in e for e in errors)


def test_validate_evidence_passes_for_real_citations():
    spec = _spec(
        recommendations=[
            KeyFinding(statement="Real trend", evidence=EvidenceRef(source_alarm_numbers=["ALARMA TGS TPS 3636"]))
        ]
    )
    errors = spec.validate_evidence(known_alarm_numbers={"ALARMA TGS TPS 3636"})
    assert errors == []


def test_validate_evidence_ignores_findings_without_evidence():
    spec = _spec(recommendations=[KeyFinding(statement="Qualitative observation, no citation needed")])
    errors = spec.validate_evidence(known_alarm_numbers=set())
    assert errors == []
