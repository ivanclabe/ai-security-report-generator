"""Minimal async PostgREST client for the app's Supabase-backed tables.

Conversations/messages/reports live in Supabase (tables prefixed "in_"),
reached over PostgREST with the anon key. That key is used server-side only
(it lives in backend/.env, never shipped to the frontend); RLS policies on
the in_* tables grant it full access scoped to just those four tables, so it
can't touch anything else in what may be a shared Supabase project.
"""
from typing import Any

import httpx

from app.config.settings import get_settings


def _client() -> httpx.AsyncClient:
    settings = get_settings()
    return httpx.AsyncClient(
        base_url=f"{settings.supabase_url}/rest/v1",
        headers={
            "apikey": settings.supabase_anon_key,
            "Authorization": f"Bearer {settings.supabase_anon_key}",
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


async def insert(table: str, data: dict[str, Any]) -> dict:
    async with _client() as client:
        response = await client.post(
            f"/{table}", json=data, headers={"Prefer": "return=representation"}
        )
        response.raise_for_status()
        return response.json()[0]


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
