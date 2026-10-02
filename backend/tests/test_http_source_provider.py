"""HttpSourceDataProvider: the DataProvider contract the agent and the tools
rely on, served by the remote source (in-memory fake) + the company registry.
Ported from the former Excel provider tests -- the figures are the same
169 July-2026 alarms of THOMAS TGS-TPS."""
from datetime import datetime, timezone

START = datetime(2026, 7, 1, tzinfo=timezone.utc)
END = datetime(2026, 7, 31, 23, 59, 59, tzinfo=timezone.utc)


async def _tps(provider):
    company = await provider.get_company(name="THOMAS TGS TPS")
    assert company is not None
    return company


# ---- companies come from the registry ----------------------------------------------


async def test_companies_come_from_the_registry_not_from_the_data(http_provider):
    company = await _tps(http_provider)
    assert (company.id, company.name) == ("thomas-tgs-tps", "THOMAS TGS TPS")
    assert company.logo_key == "Thomas TPS" and company.consecutivo == "TGS TPS"
    assert await http_provider.get_company(company_id=company.id) == company


async def test_the_old_spelling_and_the_albatroz_series_resolve_to_the_same_company(http_provider):
    by_hyphen = await http_provider.get_company(name="THOMAS TGS-TPS")
    by_series = await http_provider.get_company(name="TGS TPS")
    assert by_hyphen == by_series == await _tps(http_provider)


async def test_all_18_companies_are_available_and_ambiguous_names_are_not_guessed(http_provider):
    assert len(await http_provider.search_companies("")) == 0  # empty query is not "everything"
    assert len(await http_provider.search_companies("thomas")) == 16
    assert await http_provider.get_company(name="peru") is None  # PERU SSS or THOMAS TGS PERU?
    assert await http_provider.get_company(name="Empresa inexistente") is None


# ---- alarms -------------------------------------------------------------------------


async def test_get_security_alerts_scoped_to_period(http_provider):
    company = await _tps(http_provider)
    assert len(await http_provider.get_security_alerts(company.id, START, END)) == 169


async def test_period_filter_applies_to_the_event_date(http_provider):
    company = await _tps(http_provider)
    first_half = datetime(2026, 7, 15, 23, 59, 59, tzinfo=timezone.utc)
    alerts = await http_provider.get_security_alerts(company.id, START, first_half)
    assert 0 < len(alerts) < 169
    assert all(a.event_timestamp.replace(tzinfo=timezone.utc) <= first_half for a in alerts)


async def test_get_security_alerts_filters_by_risk_level(http_provider):
    company = await _tps(http_provider)
    critical = await http_provider.get_security_alerts(company.id, START, END, risk_level="Critico")
    assert len(critical) == 19
    assert all(a.risk_level.value == "Critico" for a in critical)
    both = await http_provider.get_security_alerts(company.id, START, END, risk_level=["Critico", "Alto"])
    assert len(both) == 19 + 59


async def test_get_security_alerts_filters_by_category(http_provider):
    company = await _tps(http_provider)
    alerts = await http_provider.get_security_alerts(company.id, START, END, category="Agente desconectado")
    assert len(alerts) == 15
    assert all(a.category == "Agente desconectado" for a in alerts)


async def test_get_security_metrics_matches_known_totals(http_provider):
    company = await _tps(http_provider)
    metrics = await http_provider.get_security_metrics(company.id, START, END)
    assert metrics.total_alerts == 169
    assert metrics.critico_alerts == 19
    assert metrics.alto_alerts == 59
    assert metrics.medio_alerts == 36
    assert metrics.bajo_alerts == 52
    assert metrics.voided_alerts == 3
    assert metrics.resolved_alerts == 150
    assert metrics.open_alerts == 19


async def test_filters_do_not_cost_extra_requests(http_provider, source_server):
    company = await _tps(http_provider)
    await http_provider.get_security_alerts(company.id, START, END)
    await http_provider.get_security_alerts(company.id, START, END, risk_level="Critico")
    await http_provider.get_security_alerts(company.id, START, END, category="Agente desconectado")
    await http_provider.get_security_metrics(company.id, START, END)
    assert len(source_server.alarm_requests) == 1


async def test_unknown_company_id_has_no_alerts_and_no_request(http_provider, source_server):
    assert await http_provider.get_security_alerts("no-existe", START, END) == []
    assert source_server.requests == []


async def test_get_alert_by_id_and_by_alarm_number(http_provider):
    company = await _tps(http_provider)
    target = (await http_provider.get_security_alerts(company.id, START, END))[0]

    by_id = await http_provider.get_alert_by_id(target.id)
    assert by_id is not None and by_id.id == target.id
    by_number = await http_provider.get_alert_by_id(target.alarm_number)
    assert by_number is not None and by_number.id == target.id


async def test_get_notifications_returns_empty_not_invented(http_provider):
    assert await http_provider.get_notifications(["21387"]) == []


async def test_email_rarity_ranking_is_reported_as_not_available(http_provider):
    company = await _tps(http_provider)
    assert await http_provider.get_top_rarity_email_recipients(company.id) is None
