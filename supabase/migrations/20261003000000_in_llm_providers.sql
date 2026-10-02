-- =============================================================================
-- Security Report Generator: Multi-LLM (Cloud / Local / vLLM / Auto).
-- Requires 20261002180000_in_auth_audit_observability.sql (membership helpers).
-- Same rules as the rest of the app: members read what they need to work,
-- admins configure; provider API keys are stored ENCRYPTED by the backend
-- (only the last 4 characters are kept in clear as a hint).
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. Provider slots (cloud, local, vllm): vendor, endpoint, key, models, params.
-- ---------------------------------------------------------------------------
create table if not exists public.in_llm_providers (
    kind text primary key check (kind in ('cloud', 'local', 'vllm')),
    vendor text not null check (vendor in ('anthropic', 'openai', 'gemini', 'vllm', 'ollama', 'openai_compatible')),
    enabled boolean not null default true,
    base_url text not null default '' check (length(base_url) <= 500),
    api_key_ciphertext text,
    api_key_hint text check (length(api_key_hint) <= 8),
    default_model text not null default '' check (length(default_model) <= 200),
    manual_models jsonb not null default '[]'::jsonb,
    discovered_models jsonb not null default '[]'::jsonb,
    discovered_at timestamptz,
    discovery_enabled boolean not null default true,
    params jsonb not null default '{}'::jsonb,
    revision integer not null default 1,
    updated_at timestamptz not null default now(),
    updated_by text references public.in_users(id)
);
alter table public.in_llm_providers enable row level security;
create policy in_llm_providers_member_read on public.in_llm_providers for select to authenticated
    using ((select public.in_is_member()));
create policy in_llm_providers_admin_insert on public.in_llm_providers for insert to authenticated
    with check ((select public.in_is_admin()));
create policy in_llm_providers_admin_update on public.in_llm_providers for update to authenticated
    using ((select public.in_is_admin())) with check ((select public.in_is_admin()));

-- ---------------------------------------------------------------------------
-- 2. Routing: default provider, AUTO priority order, health-check policy.
-- ---------------------------------------------------------------------------
create table if not exists public.in_llm_routing (
    id text primary key default 'default' check (id = 'default'),
    default_provider text not null default 'cloud' check (default_provider in ('auto', 'cloud', 'local', 'vllm')),
    auto_order jsonb not null default '["vllm", "cloud"]'::jsonb,
    health_ttl_seconds integer not null default 30 check (health_ttl_seconds between 0 and 3600),
    preflight_check boolean not null default true,
    runtime_fallback boolean not null default true,
    revision integer not null default 1,
    updated_at timestamptz not null default now(),
    updated_by text references public.in_users(id)
);
alter table public.in_llm_routing enable row level security;
create policy in_llm_routing_member_read on public.in_llm_routing for select to authenticated
    using ((select public.in_is_member()));
create policy in_llm_routing_admin_insert on public.in_llm_routing for insert to authenticated
    with check ((select public.in_is_admin()));
create policy in_llm_routing_admin_update on public.in_llm_routing for update to authenticated
    using ((select public.in_is_admin())) with check ((select public.in_is_admin()));

-- ---------------------------------------------------------------------------
-- 3. Quality evaluations (provider comparison). Admins only.
-- ---------------------------------------------------------------------------
create table if not exists public.in_llm_evaluations (
    id text primary key,
    status text not null check (status in ('queued', 'running', 'completed', 'failed')),
    candidates jsonb not null default '[]'::jsonb,
    repetitions integer not null default 1,
    results jsonb not null default '[]'::jsonb,
    summary jsonb,
    error text,
    created_by text references public.in_users(id),
    created_at timestamptz not null default now(),
    completed_at timestamptz
);
create index if not exists in_llm_evaluations_created_at_idx on public.in_llm_evaluations (created_at desc);
alter table public.in_llm_evaluations enable row level security;
create policy in_llm_evaluations_admin_read on public.in_llm_evaluations for select to authenticated
    using ((select public.in_is_admin()));
create policy in_llm_evaluations_admin_insert on public.in_llm_evaluations for insert to authenticated
    with check ((select public.in_is_admin()));
create policy in_llm_evaluations_admin_update on public.in_llm_evaluations for update to authenticated
    using ((select public.in_is_admin())) with check ((select public.in_is_admin()));

-- ---------------------------------------------------------------------------
-- 4. Which provider/model actually ran each execution (and whether it fell back).
-- ---------------------------------------------------------------------------
alter table public.in_agent_executions
    add column if not exists llm_provider text,
    add column if not exists fallback_used boolean not null default false,
    add column if not exists fallback_reason text,
    add column if not exists llm_metrics jsonb not null default '{}'::jsonb;

-- ---------------------------------------------------------------------------
-- 5. Observability: a category for LLM events (calls, health checks, fallbacks).
-- ---------------------------------------------------------------------------
alter table public.in_ops_events drop constraint if exists in_ops_events_category_check;
alter table public.in_ops_events add constraint in_ops_events_category_check
    check (category in ('request', 'auth', 'source', 'agent', 'report', 'config', 'system', 'llm'));
