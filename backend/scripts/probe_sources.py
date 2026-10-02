"""Check, from a machine that can reach the data source (VPN/LAN), that the
configuration in backend/.env really works -- and find out which `cliente=`
value the source expects for a company.

    cd backend && source .venv/bin/activate
    python scripts/probe_sources.py --company "THOMAS TGS TPS"
    python scripts/probe_sources.py --company BAC --start 2026-08-01 --end 2026-08-31 --indicators
    python scripts/probe_sources.py --company "TGS MNP" --show-rows 3

What it does
  1. Reads SOURCE_* from backend/.env (credentials are never printed).
  2. Resolves --company in the company registry (name, Albatroz series or id).
  3. Tries each plausible `cliente=` spelling with a tiny request (limite=5) and
     reports rows / columns / the client names the source returns.
  4. With the first spelling that returns data, runs the real acquisition path
     (decode + normalize + company guard) and prints an aggregate summary.
  5. --indicators also requests the indicators endpoint and shows its content type
     and the start of its body, so its format can be mapped.

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
from app.ingestion.normalizer import load_mitre_catalog  # noqa: E402
from app.ingestion.requests import (  # noqa: E402
    build_alarms_request,
    build_indicators_request,
)
from app.ingestion.service import AlarmAcquisitionService  # noqa: E402
from app.models.domain import Company  # noqa: E402
from app.services.company_registry import get_company_registry  # noqa: E402


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


async def main(args) -> int:
    settings = get_settings()
    config = SourceConfig.from_settings(settings)
    problems = config.problems()
    if problems:
        print("Configuración incompleta en backend/.env: " + "; ".join(problems))
        return 2
    print(f"Fuente: {config.base_url}  (TLS: {'verificado' if config.tls_verify else 'SIN verificar'}, "
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
    working: str | None = None
    try:
        probe_client = SourceClient(dataclasses.replace(config, alarms_limit=5))
        for candidate in _candidates(company):
            request = build_alarms_request(probe_client.config, candidate, start_dt, end_dt)
            try:
                response = await probe_client.fetch(request)
                df = decode_alarms_csv(response.content)
            except SourceError as exc:
                print(f"  cliente={candidate!r:<28} ERROR: {exc}")
                if isinstance(exc, (SourceAuthenticationError, SourceUnavailableError)):
                    return 1  # credentials/network problems do not depend on the spelling: stop here
                continue
            clients = sorted(set(df["cliente"])) if "cliente" in df.columns else []
            print(f"  cliente={candidate!r:<28} {len(df)} filas, {len(df.columns)} columnas; clientes devueltos: {clients[:5]}")
            if len(df) and working is None:
                working = candidate
                print(f"    columnas: {list(df.columns)}")
        await probe_client.aclose()

        if working is None:
            print("\nNinguna variante devolvió alarmas. Si esperabas datos, prueba otro período o revisa el nombre exacto "
                  "del cliente en la fuente y ajústalo en in_companies.source_client.")
        else:
            print(f"\nUsando cliente={working!r} para la prueba completa...")
            tested = company.model_copy(update={"source_client": working})
            acquisition = AlarmAcquisitionService(client, load_mitre_catalog(settings.mitre_tactics_path))
            batch = await acquisition.get_batch(tested, start_dt, end_dt)
            print(f"  filas recibidas: {batch.rows_received}, alarmas válidas: {len(batch.alerts)}")
            if batch.alerts:
                stamps = [a.event_timestamp for a in batch.alerts]
                print(f"  rango de fechas: {min(stamps)} -> {max(stamps)}")
                print(f"  riesgo: {dict(Counter(a.risk_level.value for a in batch.alerts))}")
                print(f"  tipos: {dict(Counter(a.alert_type for a in batch.alerts).most_common(6))}")
                print(f"  categorías distintas: {len({a.category for a in batch.alerts})}")
                print(f"  con MITRE: {sum(1 for a in batch.alerts if a.mitre_tactic_id)}")
            for warning in batch.warnings[:10]:
                print(f"  ADVERTENCIA: {warning}")
            if args.show_rows:
                print("\nPrimeras filas normalizadas:")
                for alert in batch.alerts[: args.show_rows]:
                    print("  ", json.dumps(alert.model_dump(mode="json", exclude={"raw_record"}), ensure_ascii=False)[:600])
            if working != company.request_client_name:
                print(f"\n>>> El valor que funciona ({working!r}) difiere del configurado. Para fijarlo:\n"
                      f"    update in_companies set source_client = '{working}' where id = '{company.id}';")

        if args.indicators:
            print("\nIndicadores:")
            request = build_indicators_request(config, working or company.request_client_name, start, end)
            response = await client.fetch(request)
            print(f"  HTTP {response.status_code}, {response.content_type!r}, {len(response.content)} bytes")
            body = response.content.decode("utf-8", errors="replace")
            try:
                parsed = json.loads(body)
                keys = list(parsed)[:20] if isinstance(parsed, dict) else f"lista de {len(parsed)} elementos"
                print(f"  JSON: {keys}")
            except ValueError:
                pass
            print("  inicio de la respuesta:\n    " + body[:600].replace("\n", "\n    "))
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
    parser.add_argument("--indicators", action="store_true", help="también consultar el endpoint de indicadores")
    parser.add_argument("--show-rows", type=int, default=0, help="mostrar N alarmas normalizadas (sin raw_record)")
    sys.exit(asyncio.run(main(parser.parse_args())))
