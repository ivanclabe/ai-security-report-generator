"""Regression test: Anthropic's tool-calling output has intermittently
collapsed a list field into a bare string (observed twice in production
testing against real data, not reproducible on demand). ReportNarrative
tolerates it instead of failing report generation outright."""
from app.services.report.narrative import ReportNarrative


def _base_kwargs(**overrides):
    kwargs = dict(
        objective="o",
        inventory_summary="i",
        siem_summary="s",
        network_summary="n",
        email_summary="e",
        threat_intel_summary="t",
        compromise_indicators_summary="c",
        highlighted_activities=["a"],
        recommendations=[{"statement": "r"}],
    )
    kwargs.update(overrides)
    return kwargs


def test_highlighted_activities_accepts_normal_list():
    narrative = ReportNarrative(**_base_kwargs(highlighted_activities=["a", "b"]))
    assert narrative.highlighted_activities == ["a", "b"]


def test_highlighted_activities_coerces_bare_string_to_single_item_list():
    narrative = ReportNarrative(**_base_kwargs(highlighted_activities="Solo una actividad destacada."))
    assert narrative.highlighted_activities == ["Solo una actividad destacada."]


def test_recommendations_accepts_normal_list():
    narrative = ReportNarrative(**_base_kwargs(recommendations=[{"statement": "r1"}, {"statement": "r2"}]))
    assert [r.statement for r in narrative.recommendations] == ["r1", "r2"]


def test_recommendations_coerces_bare_string_to_single_finding():
    narrative = ReportNarrative(**_base_kwargs(recommendations="Reforzar el monitoreo perimetral."))
    assert len(narrative.recommendations) == 1
    assert narrative.recommendations[0].statement == "Reforzar el monitoreo perimetral."
    assert narrative.recommendations[0].evidence is None
