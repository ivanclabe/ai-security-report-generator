"""Central company registry -- the single authority on which companies exist,
how they are named in the app/report, which logo they use and how they are
identified when asking the data source for their alarms.

Source of truth at runtime is the Supabase table `in_companies`
(editable without a deploy). The client's official list lives in
data/companies.json and is loaded into that table with
backend/scripts/seed_companies.py.

Resolution is deliberately conservative: the 18 company names share long
prefixes ("THOMAS TGS COL ..."), so a loose substring match could silently
pick the wrong company and produce a report of someone else's alarms. When a
text matches more than one company, `resolve` reports the ambiguity instead
of guessing.
"""
import difflib
import json
import logging
import re
import time
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.models.domain import Company
from app.services import supabase_rest as db

logger = logging.getLogger(__name__)

CompanyLoader = Callable[[], Awaitable[list[Company]]]

DEFAULT_CACHE_TTL_SECONDS = 60.0


def _strip_accents(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))


def company_slug(value: str) -> str:
    """Stable id for a company: 'THOMAS TGS GREG & SON' -> 'thomas-tgs-greg-son'."""
    slug = re.sub(r"[^a-z0-9]+", "-", _strip_accents(value).lower()).strip("-")
    return slug or "company"


def normalize_company_key(value: str | None) -> str:
    """Comparison key insensitive to case, accents, hyphens and spacing:
    'THOMAS TGS-TPS' and 'Thomas TGS TPS' both become 'thomas tgs tps'."""
    if not value:
        return ""
    text = re.sub(r"[^a-z0-9]+", " ", _strip_accents(value).lower())
    return " ".join(text.split())


def _identity_keys(company: Company) -> set[str]:
    """Every name the company is known by (report name, source name, Albatroz series)."""
    keys = {
        normalize_company_key(company.name),
        normalize_company_key(company.source_client),
        normalize_company_key(company.consecutivo),
    }
    keys.discard("")
    return keys


def _contains_words(haystack: str, needle: str) -> bool:
    """Whole-word containment, so 'bac' matches 'bac' but never 'abacus'."""
    return f" {needle} " in f" {haystack} "


@dataclass(frozen=True)
class CompanyMatch:
    company: Company | None = None
    candidates: list[Company] = field(default_factory=list)

    @property
    def is_ambiguous(self) -> bool:
        return self.company is None and len(self.candidates) > 1


class CompanyRegistry:
    def __init__(
        self,
        loader: CompanyLoader,
        ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._loader = loader
        self._ttl = ttl_seconds
        self._clock = clock
        self._cache: tuple[float, list[Company]] | None = None

    def invalidate(self) -> None:
        self._cache = None

    async def list_active(self) -> list[Company]:
        now = self._clock()
        if self._cache is not None and now - self._cache[0] < self._ttl:
            return list(self._cache[1])
        companies = sorted(await self._loader(), key=lambda c: c.name)
        if not companies:
            logger.warning(
                "El registro de empresas está vacío (tabla in_companies sin empresas activas). "
                "Cargar la lista oficial con: python scripts/seed_companies.py"
            )
        self._cache = (now, companies)
        return list(companies)

    async def resolve(self, text: str | None) -> CompanyMatch:
        key = normalize_company_key(text)
        if not key:
            return CompanyMatch()
        companies = await self.list_active()

        exact = [c for c in companies if key in _identity_keys(c) or company_slug(text or "") == c.id]
        if len(exact) == 1:
            return CompanyMatch(company=exact[0])
        if len(exact) > 1:
            return CompanyMatch(candidates=exact)

        partial = [
            c
            for c in companies
            if any(_contains_words(identity, key) or _contains_words(key, identity) for identity in _identity_keys(c))
        ]
        if len(partial) == 1:
            return CompanyMatch(company=partial[0])
        return CompanyMatch(candidates=partial)

    async def get(self, *, company_id: str | None = None, name: str | None = None) -> Company | None:
        if company_id:
            companies = await self.list_active()
            return next((c for c in companies if c.id == company_id), None)
        if name:
            return (await self.resolve(name)).company
        return None

    async def search(self, query: str) -> list[Company]:
        key = normalize_company_key(query)
        if not key:
            return []
        companies = await self.list_active()
        return [c for c in companies if any(key in identity for identity in _identity_keys(c))]

    async def suggest(self, text: str | None, limit: int = 5) -> list[Company]:
        """Candidates to offer the user when `text` did not resolve to one company:
        the ambiguous matches, or the closest spellings for a typo."""
        match = await self.resolve(text)
        if match.candidates:
            return match.candidates[:limit]
        key = normalize_company_key(text)
        if not key:
            return []
        companies = await self.list_active()
        by_key = {normalize_company_key(c.name): c for c in companies}
        close = difflib.get_close_matches(key, list(by_key), n=limit, cutoff=0.6)
        return [by_key[k] for k in close]


def _company_from_row(row: dict) -> Company:
    return Company(
        id=row["id"],
        name=row["name"],
        industry=row.get("industry") or "No especificado",
        country=row.get("country") or "No especificado",
        logo_key=row.get("logo_key"),
        consecutivo=row.get("consecutivo"),
        source_client=row.get("source_client"),
    )


async def load_companies_from_supabase() -> list[Company]:
    rows = await db.select("in_companies", order="name.asc")
    return [_company_from_row(r) for r in rows if r.get("is_active", True) is not False]


def load_companies_from_file(path: Path) -> list[Company]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        Company(
            id=company_slug(entry["name"]),
            name=entry["name"],
            logo_key=entry.get("logo"),
            consecutivo=entry.get("consecutivo"),
            source_client=entry.get("source_client"),
        )
        for entry in data["companies"]
    ]


def seed_rows_from_file(path: Path) -> list[dict]:
    """Rows for an idempotent upsert into in_companies. `industry`/`country`
    are not included, so re-seeding never clobbers values edited in Supabase."""
    return [
        {
            "id": c.id,
            "name": c.name,
            "logo_key": c.logo_key,
            "consecutivo": c.consecutivo,
            "source_client": c.source_client,
            "is_active": True,
        }
        for c in load_companies_from_file(path)
    ]


_registry: CompanyRegistry | None = None


def get_company_registry() -> CompanyRegistry:
    global _registry
    if _registry is None:
        _registry = CompanyRegistry(load_companies_from_supabase)
    return _registry


def set_company_registry(registry: CompanyRegistry | None) -> None:
    """Replace (or reset with None) the process-wide registry -- used by tests."""
    global _registry
    _registry = registry
