"""Load the client's official company list (data/companies.json) into the
Supabase table in_companies. Idempotent: re-running updates the same rows by id
and never touches industry/country.

in_companies is protected by RLS (admins of this app write it), so the script
signs in to Supabase Auth as an admin member -- the password is asked
interactively, never passed as an argument.

    cd backend && source .venv/bin/activate
    python scripts/seed_companies.py --dry-run                  # show what would be written
    python scripts/seed_companies.py --email admin@empresa.com  # write it (asks for the password)
"""
import argparse
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.config.settings import PROJECT_ROOT  # noqa: E402
from app.security.cli_login import sign_in_interactively  # noqa: E402
from app.services import supabase_rest as db  # noqa: E402
from app.services.company_registry import seed_rows_from_file  # noqa: E402

COMPANIES_FILE = PROJECT_ROOT / "data" / "companies.json"


async def main(dry_run: bool, email: str | None) -> None:
    rows = seed_rows_from_file(COMPANIES_FILE)
    print(f"{len(rows)} empresas en {COMPANIES_FILE.name}")
    for row in rows:
        print(f"  {row['id']:<28} {row['name']:<28} consecutivo={row['consecutivo']!r:<18} logo={row['logo_key']!r}")
    if dry_run:
        print("--dry-run: no se escribió nada.")
        return
    await sign_in_interactively(email)
    written = await db.upsert("in_companies", rows)
    print(f"OK: {len(written)} filas escritas/actualizadas en in_companies.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--email", help="correo de un administrador de la app (la contraseña se pide aparte)")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run, args.email))
