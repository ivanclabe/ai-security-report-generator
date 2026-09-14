from datetime import datetime, timezone


async def test_get_company_by_id(mock_provider):
    company = await mock_provider.get_company(company_id="acme-corp")
    assert company is not None
    assert company.name == "ACME Corp"


async def test_get_company_by_name_fuzzy(mock_provider):
    company = await mock_provider.get_company(name="acme")
    assert company is not None
    assert company.id == "acme-corp"


async def test_get_company_not_found(mock_provider):
    company = await mock_provider.get_company(name="Nonexistent Co")
    assert company is None


async def test_get_security_alerts_filters_by_date_range(mock_provider):
    start = datetime(2025, 8, 1, tzinfo=timezone.utc)
    end = datetime(2025, 8, 31, 23, 59, 59, tzinfo=timezone.utc)
    alerts = await mock_provider.get_security_alerts("acme-corp", start, end)
    assert len(alerts) > 0
    for alert in alerts:
        assert alert.client == "ACME Corp"
        assert start <= alert.event_timestamp <= end


async def test_get_security_alerts_filters_by_category(mock_provider):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 12, 31, tzinfo=timezone.utc)
    alerts = await mock_provider.get_security_alerts("acme-corp", start, end, category="Authentication")
    assert len(alerts) > 0
    assert all(a.category == "Authentication" for a in alerts)


async def test_get_security_alerts_filters_by_risk_level_list(mock_provider):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 12, 31, tzinfo=timezone.utc)
    alerts = await mock_provider.get_security_alerts("acme-corp", start, end, risk_level=["Critico", "Alto"])
    assert len(alerts) > 0
    assert all(a.risk_level.value in {"Critico", "Alto"} for a in alerts)


async def test_get_security_metrics_consistency(mock_provider):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 12, 31, tzinfo=timezone.utc)
    metrics = await mock_provider.get_security_metrics("acme-corp", start, end)
    assert metrics.total_alerts == (
        metrics.critico_alerts + metrics.alto_alerts + metrics.medio_alerts + metrics.bajo_alerts
    )
    assert metrics.total_alerts == metrics.resolved_alerts + metrics.open_alerts


async def test_alerts_scoped_to_company(mock_provider):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 12, 31, tzinfo=timezone.utc)
    acme_alerts = await mock_provider.get_security_alerts("acme-corp", start, end)
    globex_alerts = await mock_provider.get_security_alerts("globex-corp", start, end)
    acme_ids = {a.id for a in acme_alerts}
    globex_ids = {a.id for a in globex_alerts}
    assert acme_ids.isdisjoint(globex_ids)


async def test_get_alert_by_id(mock_provider):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 12, 31, tzinfo=timezone.utc)
    alerts = await mock_provider.get_security_alerts("acme-corp", start, end)
    target = alerts[0]
    found = await mock_provider.get_alert_by_id(target.id)
    assert found is not None
    assert found.id == target.id
