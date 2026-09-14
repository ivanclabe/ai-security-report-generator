from datetime import datetime, timezone

from app.tools import security_tools as tools


async def test_get_alerts_by_category_groups_correctly(mock_provider):
    params = tools.GetAlertsByCategoryParams(
        company_id="acme-corp",
        start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2025, 12, 31, tzinfo=timezone.utc),
    )
    grouped = await tools.get_alerts_by_category(mock_provider, params)
    total_from_groups = sum(len(v) for v in grouped.values())
    for category, alerts in grouped.items():
        assert all(a.category == category for a in alerts)

    all_alerts = await mock_provider.get_security_alerts(
        "acme-corp", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 12, 31, tzinfo=timezone.utc)
    )
    assert total_from_groups == len(all_alerts)


async def test_get_alert_trends_buckets_by_month(mock_provider):
    params = tools.GetAlertTrendsParams(
        company_id="acme-corp",
        start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2025, 6, 30, tzinfo=timezone.utc),
    )
    trends = await tools.get_alert_trends(mock_provider, params)
    periods = [t.period for t in trends]
    assert periods == sorted(periods)
    for t in trends:
        assert t.total_alerts >= t.critico_alerts


async def test_get_alert_trends_daily_granularity(mock_provider):
    params = tools.GetAlertTrendsParams(
        company_id="acme-corp",
        start_date=datetime(2025, 8, 1, tzinfo=timezone.utc),
        end_date=datetime(2025, 8, 7, 23, 59, 59, tzinfo=timezone.utc),
        granularity="day",
    )
    trends = await tools.get_alert_trends(mock_provider, params)
    for t in trends:
        assert len(t.period) == 10  # YYYY-MM-DD


async def test_get_security_summary_top_risk_sorted_descending(mock_provider):
    params = tools.GetSecuritySummaryParams(
        company_id="acme-corp",
        start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2025, 12, 31, tzinfo=timezone.utc),
    )
    summary = await tools.get_security_summary(mock_provider, params)
    scores = [a.severity_score for a in summary.top_risk_alerts]
    assert scores == sorted(scores, reverse=True)
    assert summary.metrics.total_alerts >= len(summary.top_risk_alerts)


async def test_get_mitre_analysis_groups_and_sorts_by_count(mock_provider):
    params = tools.GetMitreAnalysisParams(
        company_id="acme-corp",
        start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2026, 12, 31, tzinfo=timezone.utc),
    )
    analysis = await tools.get_mitre_analysis(mock_provider, params)
    # mock data has no MITRE info -- every alert should land in "without_mitre_data",
    # and the tool must say so rather than inventing tactics.
    assert analysis.tactics == []
    assert analysis.alerts_without_mitre_data > 0


async def test_get_response_metrics_rate_and_timing(mock_provider):
    params = tools.GetResponseMetricsParams(
        company_id="acme-corp",
        start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2026, 12, 31, tzinfo=timezone.utc),
    )
    metrics = await tools.get_response_metrics(mock_provider, params)
    assert metrics.total_alerts == metrics.with_response + metrics.without_response
    assert 0 <= metrics.response_rate_pct <= 100
    if metrics.with_response:
        assert metrics.average_response_time_hours is not None
