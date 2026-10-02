"""Minimal async PostgREST client for the app's Supabase-backed tables.

Every request is made **as the signed-in user**: the `apikey` header carries
the project's public anon key (it only identifies the project), and
`Authorization` carries the user's Supabase Auth access token taken from the
request context (app/security/context.py). Row Level Security then decides
what that user may read or write -- membership of this app and, for admin
areas, the admin role (supabase/migrations/*_in_auth_audit_observability.sql).

Without a user in context the anon key is used, which RLS denies on every
in_* table: only the narrow public RPC for authentication-failure audit
events (in_log_auth_event) works that way.
"""
from typing import Any

import httpx

from app.config.settings import get_settings
from app.security.context import get_access_token


class SupabaseNotConfigured(RuntimeError):
    pass


def _client(*, as_anon: bool = False) -> httpx.AsyncClient:
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise SupabaseNotConfigured("Supabase no está configurado (SUPABASE_URL / SUPABASE_ANON_KEY).")
    token = None if as_anon else get_access_token()
    return httpx.AsyncClient(
        base_url=f"{settings.supabase_url}/rest/v1",
        headers={
            "apikey": settings.supabase_anon_key,
            "Authorization": f"Bearer {token or settings.supabase_anon_key}",
            "Content-Type": "application/json",
        },
        timeout=10.0,
    )


def _eq_params(filters: dict[str, Any] | None) -> dict[str, str]:
    if not filters:
        return {}
    return {key: f"eq.{value}" for key, value in filters.items()}


async def select(
    table: str,
    filters: dict[str, Any] | None = None,
    order: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    params = _eq_params(filters)
    if order:
        params["order"] = order
    if limit:
        params["limit"] = str(limit)
    async with _client() as client:
        response = await client.get(f"/{table}", params=params)
        response.raise_for_status()
        return response.json()


async def query(table: str, params: list[tuple[str, str]], *, count: bool = False) -> tuple[list[dict], int | None]:
    """Raw PostgREST query (operators such as gte./ilike./in., select=, offset=) with an
    optional exact total for pagination. Callers build `params` from validated input only."""
    headers = {"Prefer": "count=exact"} if count else {}
    async with _client() as client:
        response = await client.get(f"/{table}", params=params, headers=headers)
        response.raise_for_status()
        total = None
        if count:
            content_range = response.headers.get("content-range", "")
            tail = content_range.rsplit("/", 1)[-1]
            total = int(tail) if tail.isdigit() else None
        return response.json(), total


async def insert(table: str, data: dict[str, Any]) -> dict:
    async with _client() as client:
        response = await client.post(
            f"/{table}", json=data, headers={"Prefer": "return=representation"}
        )
        response.raise_for_status()
        return response.json()[0]


async def insert_quiet(table: str, data: dict[str, Any]) -> None:
    """Insert without reading the row back -- for write-only tables (audit, ops events),
    whose rows the writer is not allowed to SELECT under RLS."""
    async with _client() as client:
        response = await client.post(f"/{table}", json=data, headers={"Prefer": "return=minimal"})
        response.raise_for_status()


async def upsert(table: str, rows: list[dict[str, Any]], on_conflict: str = "id") -> list[dict]:
    """Insert-or-update by `on_conflict` column (PostgREST merge-duplicates)."""
    async with _client() as client:
        response = await client.post(
            f"/{table}",
            params={"on_conflict": on_conflict},
            json=rows,
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        )
        response.raise_for_status()
        return response.json()


async def update(table: str, filters: dict[str, Any], data: dict[str, Any]) -> dict | None:
    params = _eq_params(filters)
    async with _client() as client:
        response = await client.patch(
            f"/{table}", params=params, json=data, headers={"Prefer": "return=representation"}
        )
        response.raise_for_status()
        rows = response.json()
        return rows[0] if rows else None


async def delete(table: str, filters: dict[str, Any]) -> None:
    params = _eq_params(filters)
    async with _client() as client:
        response = await client.delete(f"/{table}", params=params)
        response.raise_for_status()


async def rpc(function: str, args: dict[str, Any], *, as_anon: bool = False) -> Any:
    async with _client(as_anon=as_anon) as client:
        response = await client.post(f"/rpc/{function}", json=args)
        response.raise_for_status()
        return response.json() if response.content else None
