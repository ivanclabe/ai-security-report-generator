"""Company registry: the client's official list (data/companies.json), how a
free-text company reference is resolved against it, and the Supabase loader."""
import logging

import pytest

from app.services.company_registry import (
    CompanyRegistry,
    company_slug,
    load_companies_from_file,
    load_companies_from_supabase,
    normalize_company_key,
    seed_rows_from_file,
)
from tests.conftest import COMPANIES_FILE_PATH

# Exactly the table the client shared: (Nombre empresa informe, Logo, Consecutivo Albatroz).
CLIENT_LIST = [
    ("THOMAS TGS COL TTI", "Thomas Colombia", "TGS COL TTI"),
    ("THOMAS TGS GREG & SON", "Thomas Colombia", "TGS MNP"),
    ("THOMAS TGS COLOMBIA", "Thomas Colombia", "TGS COL"),
    ("THOMAS TGS COL LOTERIAS", "Thomas Colombia", "TGS COL LOT"),
    ("THOMAS TGS TPS", "Thomas TPS", "TGS TPS"),
    ("THOMAS TGS LIMITED", "TGS Limited", "TGS LTD"),
    ("BAC", "BAC", "BAC"),
    ("THOMAS TGS SECURID", "SecurID", "TGS SCD"),
    ("THOMAS TGS CSC", "TGS CSC", "TGS CSC"),
    ("THOMAS TGS MTI", "TGS MTI", "TGS MTI"),
    ("THOMAS TGS EXPRESS", "TGS EXPRESS", "TGS EXP"),
    ("THOMAS TGS TURRISYSTEM", "TGS TURRISYSTEM", "TGS TUR"),
    ("PERU SSS", "PERU SSS", "PERU SSS"),
    ("THOMAS TGS SIR", "TGS SIR", "TGS SIR"),
    ("THOMAS TGS BRASIL", "TGS BRASIL", "TGS BR"),
    ("THOMAS TGS MEXICO", "TGS MEXICO", "TGS MX"),
    ("THOMAS TGS PERU", "TGS PERU", "TGS PERU"),
    ("THOMAS TGS INVOTECSA", "INVOTECSA", "TGS INVOTECSA"),
]


@pytest.fixture
def registry():
    async def loader():
        return load_companies_from_file(COMPANIES_FILE_PATH)

    return CompanyRegistry(loader)


# ---- the official list ----------------------------------------------------


def test_seed_file_matches_the_client_list_exactly():
    companies = load_companies_from_file(COMPANIES_FILE_PATH)
    assert [(c.name, c.logo_key, c.consecutivo) for c in companies] == CLIENT_LIST


def test_seed_file_ids_and_consecutivos_are_unique():
    companies = load_companies_from_file(COMPANIES_FILE_PATH)
    assert len({c.id for c in companies}) == len(companies) == 18
    assert len({c.consecutivo for c in companies}) == 18


def test_tps_keeps_the_id_it_already_had_in_supabase():
    # in_companies already had 'thomas-tgs-tps' (FK target of in_data_sources/in_data_imports);
    # the official name 'THOMAS TGS TPS' must slug to the same id.
    assert company_slug("THOMAS TGS TPS") == "thomas-tgs-tps"
    assert company_slug("THOMAS TGS-TPS") == "thomas-tgs-tps"


def test_slug_handles_ampersand():
    assert company_slug("THOMAS TGS GREG & SON") == "thomas-tgs-greg-son"


def test_seed_rows_never_overwrite_industry_or_country():
    rows = seed_rows_from_file(COMPANIES_FILE_PATH)
    assert len(rows) == 18
    assert all("industry" not in r and "country" not in r for r in rows)
    assert all(r["is_active"] is True for r in rows)
    # every company declares the exact cliente= value the source accepts
    assert all(r["source_client"] for r in rows)


def test_every_company_requests_a_client_name_the_source_actually_offers():
    """The source's indicators page lists the exact cliente= values it accepts;
    each of the 18 companies must map to one of them (a typo here silently means
    'no alarms')."""
    from tests.source_fakes import SOURCE_CLIENT_OPTIONS

    companies = load_companies_from_file(COMPANIES_FILE_PATH)
    mapping = {c.name: c.request_client_name for c in companies}
    assert set(mapping.values()) <= set(SOURCE_CLIENT_OPTIONS)
    assert len(set(mapping.values())) == 18  # no two companies share a source client
    assert mapping["THOMAS TGS GREG & SON"] == "THOMAS TGS-GREG"
    assert mapping["PERU SSS"] == "PERU-SSS"
    assert mapping["THOMAS TGS LIMITED"] == "THOMAS TGS LIMITED"  # this one has no hyphen at the source


def test_source_clients_outside_the_official_list_are_not_registered():
    from tests.source_fakes import SOURCE_CLIENT_OPTIONS

    registered = {c.request_client_name for c in load_companies_from_file(COMPANIES_FILE_PATH)}
    assert set(SOURCE_CLIENT_OPTIONS) - registered == {"THOMAS GREG & SONS", "AIRE", "THOMAS TGS-ALTA-GERENCIA"}


# ---- normalization & resolution -------------------------------------------


def test_normalization_ignores_case_accents_hyphens_and_spacing():
    assert normalize_company_key("THOMAS TGS-TPS") == normalize_company_key("  Thomas   tgs tps ")
    assert normalize_company_key("Perú  SSS") == "peru sss"
    assert normalize_company_key(None) == ""


@pytest.mark.parametrize(
    "text, expected",
    [
        ("THOMAS TGS TPS", "THOMAS TGS TPS"),
        ("THOMAS TGS-TPS", "THOMAS TGS TPS"),  # spelling used by the old Excel export
        ("thomas tgs tps", "THOMAS TGS TPS"),
        ("TGS TPS", "THOMAS TGS TPS"),  # Consecutivo Albatroz
        ("TGS MNP", "THOMAS TGS GREG & SON"),  # consecutivo that does not look like the name
        ("thomas-tgs-greg-son", "THOMAS TGS GREG & SON"),  # id
        ("BAC", "BAC"),
        ("TGS COL", "THOMAS TGS COLOMBIA"),  # exact consecutivo beats the longer 'TGS COL ...' ones
        ("THOMAS TGS COLOMBIA", "THOMAS TGS COLOMBIA"),
    ],
)
async def test_resolves_exact_identities(registry, text, expected):
    match = await registry.resolve(text)
    assert match.company is not None and match.company.name == expected


async def test_resolves_unique_partial_text(registry):
    assert (await registry.resolve("tps")).company.name == "THOMAS TGS TPS"
    assert (await registry.resolve("Genera el informe de THOMAS TGS TPS para julio")).company.name == (
        "THOMAS TGS TPS"
    )


async def test_ambiguous_text_is_reported_not_guessed(registry):
    match = await registry.resolve("thomas tgs col")
    assert match.company is None and match.is_ambiguous
    assert {c.name for c in match.candidates} == {
        "THOMAS TGS COL TTI",
        "THOMAS TGS COL LOTERIAS",
        "THOMAS TGS COLOMBIA",  # its consecutivo 'TGS COL' is contained in what the user typed
    }

    peru = await registry.resolve("peru")
    assert peru.company is None
    assert {c.name for c in peru.candidates} == {"PERU SSS", "THOMAS TGS PERU"}


async def test_partial_match_respects_word_boundaries(registry):
    match = await registry.resolve("abacus")
    assert match.company is None and match.candidates == []


async def test_unknown_company_resolves_to_nothing(registry):
    match = await registry.resolve("Empresa Inexistente")
    assert match.company is None and match.candidates == []
    assert (await registry.resolve("")).company is None
    assert (await registry.resolve(None)).company is None


async def test_get_by_id_and_by_name(registry):
    assert (await registry.get(company_id="bac")).name == "BAC"
    assert await registry.get(company_id="no-existe") is None
    assert (await registry.get(name="THOMAS TGS-TPS")).id == "thomas-tgs-tps"
    assert await registry.get(name="peru") is None  # ambiguous => no silent pick
    assert await registry.get() is None


async def test_search(registry):
    names = {c.name for c in await registry.search("col")}
    assert {"THOMAS TGS COLOMBIA", "THOMAS TGS COL TTI", "THOMAS TGS COL LOTERIAS"} <= names
    assert await registry.search("") == []


async def test_suggest_offers_candidates_or_close_spellings(registry):
    ambiguous = await registry.suggest("peru")
    assert {c.name for c in ambiguous} == {"PERU SSS", "THOMAS TGS PERU"}
    typo = await registry.suggest("THOMAS TGS COLOMBA")
    assert typo and typo[0].name == "THOMAS TGS COLOMBIA"
    assert await registry.suggest("zzzzzz") == []


async def test_request_client_name_defaults_to_report_name_and_can_be_overridden(registry):
    bac = await registry.get(company_id="bac")
    assert bac.request_client_name == "BAC"
    # TPS is spelled 'THOMAS TGS-TPS' at the source (old export + the client's example URLs)
    tps = await registry.get(company_id="thomas-tgs-tps")
    assert (tps.name, tps.request_client_name) == ("THOMAS TGS TPS", "THOMAS TGS-TPS")


# ---- Supabase loader & cache ----------------------------------------------


async def test_supabase_loader_maps_columns_and_skips_inactive(fake_supabase):
    table = fake_supabase.table("in_companies")
    table.rows.clear()
    table.insert({"id": "a", "name": "A", "logo_key": "Logo A", "consecutivo": "TGS A", "source_client": "A-SRC",
                  "industry": None, "country": None, "is_active": True})
    table.insert({"id": "b", "name": "B", "is_active": False})
    table.insert({"id": "c", "name": "C"})  # row predating the is_active column counts as active

    companies = await load_companies_from_supabase()

    assert [c.id for c in companies] == ["a", "c"]
    a = companies[0]
    assert (a.logo_key, a.consecutivo, a.request_client_name) == ("Logo A", "TGS A", "A-SRC")
    assert a.industry == "No especificado"


async def test_changing_a_company_in_supabase_is_picked_up_after_the_ttl(fake_supabase):
    clock = {"now": 0.0}
    registry = CompanyRegistry(load_companies_from_supabase, ttl_seconds=60, clock=lambda: clock["now"])
    assert [c.id for c in await registry.list_active()] == ["acme-corp"]

    fake_supabase.table("in_companies").insert({"id": "new-co", "name": "New Co", "is_active": True})
    clock["now"] = 30
    assert [c.id for c in await registry.list_active()] == ["acme-corp"]  # still cached
    clock["now"] = 61
    assert {c.id for c in await registry.list_active()} == {"acme-corp", "new-co"}

    fake_supabase.table("in_companies").rows[0]["is_active"] = False
    registry.invalidate()
    assert [c.id for c in await registry.list_active()] == ["new-co"]


async def test_empty_registry_logs_how_to_seed_it(caplog):
    async def empty():
        return []

    with caplog.at_level(logging.WARNING):
        assert await CompanyRegistry(empty).list_active() == []
    assert "seed_companies.py" in caplog.text
