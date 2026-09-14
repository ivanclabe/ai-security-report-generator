from datetime import datetime, timezone


async def test_company_derived_from_client_column(excel_provider):
    company = await excel_provider.get_company(name="THOMAS TGS-TPS")
    assert company is not None
    assert company.name == "THOMAS TGS-TPS"

    by_id = await excel_provider.get_company(company_id=company.id)
    assert by_id == company


async def test_no_ingestion_warnings_for_the_shipped_fixture(excel_provider):
    assert excel_provider.ingestion_warnings == []


async def test_get_security_alerts_scoped_to_period(excel_provider):
    company = await excel_provider.get_company(name="THOMAS TGS-TPS")
    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 31, 23, 59, 59, tzinfo=timezone.utc)
    alerts = await excel_provider.get_security_alerts(company.id, start, end)
    assert len(alerts) == 169


async def test_get_security_alerts_filters_by_risk_level(excel_provider):
    company = await excel_provider.get_company(name="THOMAS TGS-TPS")
    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 31, 23, 59, 59, tzinfo=timezone.utc)
    critical = await excel_provider.get_security_alerts(company.id, start, end, risk_level="Critico")
    assert len(critical) == 19
    assert all(a.risk_level.value == "Critico" for a in critical)


async def test_get_security_alerts_filters_by_category(excel_provider):
    company = await excel_provider.get_company(name="THOMAS TGS-TPS")
    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 31, 23, 59, 59, tzinfo=timezone.utc)
    alerts = await excel_provider.get_security_alerts(company.id, start, end, category="Agente desconectado")
    assert len(alerts) == 15
    assert all(a.category == "Agente desconectado" for a in alerts)


async def test_get_security_metrics_matches_known_totals(excel_provider):
    company = await excel_provider.get_company(name="THOMAS TGS-TPS")
    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 31, 23, 59, 59, tzinfo=timezone.utc)
    metrics = await excel_provider.get_security_metrics(company.id, start, end)
    assert metrics.total_alerts == 169
    assert metrics.critico_alerts == 19
    assert metrics.alto_alerts == 59
    assert metrics.medio_alerts == 36
    assert metrics.bajo_alerts == 52
    assert metrics.voided_alerts == 3
    assert metrics.resolved_alerts == 150
    assert metrics.open_alerts == 19


async def test_get_alert_by_id_and_by_alarm_number(excel_provider):
    company = await excel_provider.get_company(name="THOMAS TGS-TPS")
    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 31, 23, 59, 59, tzinfo=timezone.utc)
    alerts = await excel_provider.get_security_alerts(company.id, start, end)
    target = alerts[0]

    by_id = await excel_provider.get_alert_by_id(target.id)
    assert by_id is not None
    assert by_id.id == target.id

    by_number = await excel_provider.get_alert_by_id(target.alarm_number)
    assert by_number is not None
    assert by_number.id == target.id


async def test_get_notifications_returns_empty_not_invented(excel_provider):
    notifications = await excel_provider.get_notifications(["21387"])
    assert notifications == []
