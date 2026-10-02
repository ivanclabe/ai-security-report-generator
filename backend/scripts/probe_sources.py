"""Check, from a machine that can reach the data source (VPN/LAN), that the
configuration in backend/.env really works -- and find out which `cliente=`
value the source expects for a company.

    cd backend && source .venv/bin/activate
    python scripts/probe_sources.py --company "THOMAS TGS TPS" --indicators
    python scripts/probe_sources.py --company BAC --start 2026-08-01 --end 2026-08-31
    python scripts/probe_sources.py --company "TGS MNP" --show-rows 3

What it does
  1. Reads SOURCE_* from backend/.env (credentials are never printed).
  2. Resolves --company in the company registry (name, Albatroz series or id).
  3. Tries each plausible `cliente=` spelling with a tiny request (limite=5) and
     reports rows / columns / the client names the source returns, and which
     authentication was needed (Basic Auth or the login form).
  4. With the first spelling that returns data, runs the real acquisition path
     (decode + normalize + company guard + reconciliation with the indicators
     page) and prints an aggregate summary.
  5. --indicators also reads the indicators page (indicadores.php): totals, tops,
     per-day, categories, and compares the source's client list with the registry.

Paste the output (it contains no credentials) back to the developer if a column
or a client name does not match what the app expects.
"""
import argparse
import asyncio
import dataclasses
import json
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.config.settings import get_settings  # noqa: E402
from app.ingestion.client import SourceClient  # noqa: E402
from app.ingestion.config import SourceConfig  # noqa: E402
from app.ingestion.csv_decoder import decode_alarms_csv  # noqa: E402
from app.ingestion.errors import (  # noqa: E402
    SourceAuthenticationError,
    SourceError,
    SourceUnavailableError,
)
from app.ingestion.indicators_parser import parse_indicators_page  # noqa: E402
from app.ingestion.normalizer import load_mitre_catalog  # noqa: E402
from app.ingestion.requests import (  # noqa: E402
    build_alarms_request,
    build_indicators_request,
)
from app.ingestion.service import AlarmAcquisitionService  # noqa: E402
from app.models.domain import Company  # noqa: E402
from app.services.company_registry import get_company_registry  # noqa: E402

_STOP = object()


def _candidates(company: Company) -> list[str]:
    words = company.name.split()
    values = [
        company.request_client_name,
        company.name,
        company.consecutivo or "",
        " ".join(words[:-1]) + "-" + words[-1] if len(words) > 1 else "",  # 'THOMAS TGS TPS' -> 'THOMAS TGS-TPS'
    ]
    seen: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return seen


def _last_full_month() -> tuple[date, date]:
    first_this = date.today().replace(day=1)
    last_prev = first_this - timedelta(days=1)
    return last_prev.replace(day=1), last_prev


async def _probe_spellings(config: SourceConfig, company: Company, start_dt, end_dt):
    """First `cliente=` spelling that returns rows, None if none does, _STOP on auth/network errors."""
    probe_client = SourceClient(dataclasses.replace(config, alarms_limit=5))
    working: str | None = None
    try:
        for candidate in _candidates(company):
            request = build_alarms_request(probe_client.config, candidate, start_dt, end_dt)
            try:
                df = decode_alarms_csv((await probe_client.fetch(request)).content)
            except SourceError as exc:
                print(f"  cliente={candidate!r:<28} ERROR: {exc}")
                if isinstance(exc, (SourceAuthenticationError, SourceUnavailableError)):
                    return _STOP  # credentials/network problems do not depend on the spelling
                continue
            clients = sorted(set(df["cliente"])) if "cliente" in df.columns else []
            print(f"  cliente={candidate!r:<28} {len(df)} filas, {len(df.columns)} columnas; clientes devueltos: {clients[:5]}")
            if len(df) and working is None:
                working = candidate
                print(f"    columnas: {list(df.columns)}")
        print(f"  autenticación usada: {probe_client.last_login_method or 'ninguna'}")
    finally:
        await probe_client.aclose()
    return working


async def _full_acquisition(client, settings, company, working, start_dt, end_dt, show_rows: int) -> None:
    print(f"\nUsando cliente={working!r} para la prueba completa...")
    tested = company.model_copy(update={"source_client": working})
    acquisition = AlarmAcquisitionService(client, load_mitre_catalog(settings.mitre_tactics_path))
    batch = await acquisition.get_batch(tested, start_dt, end_dt)
    print(f"  filas recibidas: {batch.rows_received}, alarmas válidas: {len(batch.alerts)}")
    if batch.alerts:
        stamps = [a.event_timestamp for a in batch.alerts]
        print(f"  rango de fechas: {min(stamps)} -> {max(stamps)}")
        print(f"  riesgo (clasificación del informe): {dict(Counter(a.risk_level.value for a in batch.alerts))}")
        print(f"  tipos: {dict(Counter(a.alert_type for a in batch.alerts).most_common(6))}")
        print(f"  categorías distintas: {len({a.category for a in batch.alerts})}")
        print(f"  con MITRE: {sum(1 for a in batch.alerts if a.mitre_tactic_id)}")
    for warning in batch.warnings[:10]:
        print(f"  ADVERTENCIA: {warning}")
    if show_rows:
        print("\nPrimeras filas normalizadas:")
        for alert in batch.alerts[:show_rows]:
            print("  ", json.dumps(alert.model_dump(mode="json", exclude={"raw_record"}), ensure_ascii=False)[:600])
    if working != company.request_client_name:
        print(f"\n>>> El valor que funciona ({working!r}) difiere del configurado. Para fijarlo:\n"
              f"    update in_companies set source_client = '{working}' where id = '{company.id}';")


async def _indicators(client, config, client_value: str, start: date, end: date) -> None:
    print("\nIndicadores (indicadores.php):")
    response = await client.fetch(build_indicators_request(config, client_value, start, end))
    print(f"  HTTP {response.status_code}, {response.content_type!r}, {len(response.content)} bytes")
    ind = parse_indicators_page(response.content)
    print(f"  cliente mostrado: {ind.client!r}  período de la página: {ind.start_date} a {ind.end_date} "
          "(fecha_fin exclusiva)")
    print(f"  total de alarmas: {ind.total_alarms} (registros listados: {len(ind.records)}), "
          f"principal origen: {ind.principal_source_ip}")
    print(f"  riesgo (bandas de la fuente): {[(r.level, r.range_label, r.percent) for r in ind.risk_distribution]}")
    print(f"  por tipo: {[(c.label, c.count) for c in ind.alarms_by_type]}")
    print(f"  días con alarmas: {len(ind.alarms_by_day)}; top categorías: "
          f"{[(c.label, c.count) for c in ind.top_categories[:5]]}")
    for warning in ind.warnings:
        print(f"  ADVERTENCIA: {warning}")

    registry = await get_company_registry().list_active()
    requested = {c.request_client_name: c.name for c in registry}
    offered = set(ind.available_clients)
    missing = {name: value for value, name in requested.items() if value not in offered}
    print(f"\n  la fuente ofrece {len(offered)} clientes; registradas {len(registry)} empresas")
    if missing:
        print("  EMPRESAS CUYO cliente= NO EXISTE EN LA FUENTE (no traerán datos):")
        for name, value in missing.items():
            print(f"    {name}: cliente={value!r}")
    else:
        print("  todas las empresas registradas piden un cliente que la fuente ofrece.")
    extra = sorted(offered - set(requested))
    if extra:
        print(f"  clientes de la fuente fuera de la lista oficial: {extra}")


async def main(args) -> int:
    settings = get_settings()
    config = SourceConfig.from_settings(settings)
    problems = config.problems()
    if problems:
        print("Configuración incompleta en backend/.env: " + "; ".join(problems))
        return 2
    if config.base_url.startswith("http://"):
        tls = "SIN TLS: http en claro"
    else:
        tls = "TLS verificado" if config.tls_verify else "TLS SIN verificar"
    print(f"Fuente: {config.base_url}  ({tls}, "
          f"timeout {config.timeout_seconds:g}s, usuario configurado)")

    match = await get_company_registry().resolve(args.company)
    if match.company is None:
        options = ", ".join(c.name for c in match.candidates) or "ninguna coincidencia"
        print(f"No pude identificar la empresa '{args.company}' en el registro ({options}).")
        return 2
    company = match.company
    start = date.fromisoformat(args.start) if args.start else _last_full_month()[0]
    end = date.fromisoformat(args.end) if args.end else _last_full_month()[1]
    print(f"Empresa: {company.name}  (id={company.id}, consecutivo={company.consecutivo!r}, "
          f"cliente= configurado: {company.request_client_name!r})")
    print(f"Período: {start} a {end}\n")

    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end, datetime.max.time()).replace(microsecond=0)
    client = SourceClient(config)
    try:
        working = await _probe_spellings(config, company, start_dt, end_dt)
        if working is _STOP:
            return 1
        if working is None:
            print("\nNinguna variante devolvió alarmas en el export CSV.")
        else:
            await _full_acquisition(client, settings, company, working, start_dt, end_dt, args.show_rows)
        if args.indicators:
            await _indicators(client, config, working or company.request_client_name, start, end)
    except SourceError as exc:
        print(f"\nERROR: {exc}")
        return 1
    finally:
        await client.aclose()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--company", required=True, help="nombre, serie Albatroz o id de la empresa")
    parser.add_argument("--start", help="YYYY-MM-DD (por defecto: primer día del mes anterior)")
    parser.add_argument("--end", help="YYYY-MM-DD (por defecto: último día del mes anterior)")
    parser.add_argument("--indicators", action="store_true", help="también leer la página de indicadores")
    parser.add_argument("--show-rows", type=int, default=0, help="mostrar N alarmas normalizadas (sin raw_record)")
    sys.exit(asyncio.run(main(parser.parse_args())))
