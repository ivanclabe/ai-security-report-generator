-- =============================================================================
-- Security Report Generator: Supabase Auth, membership, RLS, audit log,
-- observability events, user preferences and data-source settings.
--
-- Context: this Supabase project is SHARED with other applications, and its
-- auth.users already holds accounts of those apps. "authenticated" alone is
-- therefore NOT authorization: every policy below requires an active row in
-- public.in_users linked to auth.uid() (membership of THIS app), and admin-only
-- areas require role = 'admin'. The anon role loses all access to in_* tables
-- (it had full read/write before, and the anon key is public in the other
-- apps' frontends).
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. Membership: in_users becomes the app's member list, linked to Supabase Auth
--    (no passwords here -- Supabase Auth owns credentials).
-- ---------------------------------------------------------------------------
alter table public.in_users
    add column if not exists auth_user_id uuid unique references auth.users(id) on delete cascade,
    add column if not exists email text,
    add column if not exists is_active boolean not null default true,
    add column if not exists last_seen_at timestamptz;

alter table public.in_users drop constraint if exists in_users_role_check;
update public.in_users set role = 'admin' where role not in ('admin', 'operator');
alter table public.in_users add constraint in_users_role_check check (role in ('admin', 'operator'));

-- The legacy shared 'master' login has no Supabase Auth account: it can no longer sign in.
update public.in_users set is_active = false where auth_user_id is null;

create or replace function public.in_member_id()
returns text language sql stable security definer set search_path = '' as $$
    select id from public.in_users where auth_user_id = (select auth.uid()) and is_active limit 1
$$;

create or replace function public.in_is_member()
returns boolean language sql stable security definer set search_path = '' as $$
    select exists (select 1 from public.in_users where auth_user_id = (select auth.uid()) and is_active)
$$;

create or replace function public.in_is_admin()
returns boolean language sql stable security definer set search_path = '' as $$
    select exists (
        select 1 from public.in_users where auth_user_id = (select auth.uid()) and is_active and role = 'admin'
    )
$$;

revoke execute on function public.in_member_id(), public.in_is_member(), public.in_is_admin() from public, anon;
grant execute on function public.in_member_id(), public.in_is_member(), public.in_is_admin() to authenticated;

-- ---------------------------------------------------------------------------
-- 2. Existing tables: drop the anon-wide policies, members only.
-- ---------------------------------------------------------------------------
drop policy if exists in_companies_anon_all on public.in_companies;
drop policy if exists in_users_anon_all on public.in_users;
drop policy if exists in_report_templates_anon_all on public.in_report_templates;
drop policy if exists in_data_sources_anon_all on public.in_data_sources;
drop policy if exists in_data_imports_anon_all on public.in_data_imports;
drop policy if exists in_agent_executions_anon_all on public.in_agent_executions;
drop policy if exists in_conversations_anon_all on public.in_conversations;
drop policy if exists in_messages_anon_all on public.in_messages;
drop policy if exists in_reports_anon_all on public.in_reports;
drop policy if exists in_report_versions_anon_all on public.in_report_versions;

-- Reference data: every member reads, admins maintain.
create policy in_companies_member_read on public.in_companies for select to authenticated using ((select public.in_is_member()));
create policy in_companies_admin_write on public.in_companies for all to authenticated
    using ((select public.in_is_admin())) with check ((select public.in_is_admin()));
create policy in_report_templates_member_read on public.in_report_templates for select to authenticated using ((select public.in_is_member()));
create policy in_report_templates_admin_write on public.in_report_templates for all to authenticated
    using ((select public.in_is_admin())) with check ((select public.in_is_admin()));

-- Members: each user sees their own row; admins see and manage everyone. No deletes (deactivate instead).
create policy in_users_self_or_admin_read on public.in_users for select to authenticated
    using (auth_user_id = (select auth.uid()) or (select public.in_is_admin()));
create policy in_users_admin_insert on public.in_users for insert to authenticated with check ((select public.in_is_admin()));
create policy in_users_admin_update on public.in_users for update to authenticated
    using ((select public.in_is_admin())) with check ((select public.in_is_admin()));

-- Report work is shared by the SOC team: every member works on it.
create policy in_conversations_member_all on public.in_conversations for all to authenticated
    using ((select public.in_is_member())) with check ((select public.in_is_member()));
create policy in_messages_member_all on public.in_messages for all to authenticated
    using ((select public.in_is_member())) with check ((select public.in_is_member()));
create policy in_reports_member_all on public.in_reports for all to authenticated
    using ((select public.in_is_member())) with check ((select public.in_is_member()));
create policy in_report_versions_member_all on public.in_report_versions for all to authenticated
    using ((select public.in_is_member())) with check ((select public.in_is_member()));

-- Execution / import trails: members write them while working; nobody deletes them.
create policy in_agent_executions_member_read on public.in_agent_executions for select to authenticated using ((select public.in_is_member()));
create policy in_agent_executions_member_insert on public.in_agent_executions for insert to authenticated with check ((select public.in_is_member()));
create policy in_agent_executions_member_update on public.in_agent_executions for update to authenticated
    using ((select public.in_is_member())) with check ((select public.in_is_member()));
create policy in_data_sources_member_read on public.in_data_sources for select to authenticated using ((select public.in_is_member()));
create policy in_data_sources_member_insert on public.in_data_sources for insert to authenticated with check ((select public.in_is_member()));
create policy in_data_imports_member_read on public.in_data_imports for select to authenticated using ((select public.in_is_member()));
create policy in_data_imports_member_insert on public.in_data_imports for insert to authenticated with check ((select public.in_is_member()));

-- ---------------------------------------------------------------------------
-- 3. Data-source settings (Fuente de Datos). One row. The source password is
--    stored ENCRYPTED by the backend (Fernet, key only in the backend's
--    environment): readable rows never expose it in clear.
-- ---------------------------------------------------------------------------
create table if not exists public.in_source_settings (
    id text primary key default 'default' check (id = 'default'),
    scheme text not null default 'http' check (scheme in ('http', 'https')),
    host text not null check (length(host) between 1 and 253),
    base_path text not null default '' check (length(base_path) <= 512),
    alarms_path text not null default '/detallado_alarmas.php' check (length(alarms_path) <= 1024),
    notifications_path text not null default '/indicadores.php' check (length(notifications_path) <= 1024),
    username text check (length(username) <= 256),
    password_ciphertext text,
    verify_tls boolean not null default true,
    timeout_seconds numeric not null default 30 check (timeout_seconds between 1 and 300),
    alarms_limit integer not null default 1000 check (alarms_limit between 1 and 100000),
    reconcile_indicators boolean not null default true,
    revision integer not null default 1,
    updated_at timestamptz not null default now(),
    updated_by text references public.in_users(id)
);
alter table public.in_source_settings enable row level security;
create policy in_source_settings_member_read on public.in_source_settings for select to authenticated using ((select public.in_is_member()));
create policy in_source_settings_admin_insert on public.in_source_settings for insert to authenticated with check ((select public.in_is_admin()));
create policy in_source_settings_admin_update on public.in_source_settings for update to authenticated
    using ((select public.in_is_admin())) with check ((select public.in_is_admin()));

-- ---------------------------------------------------------------------------
-- 4. Per-user preferences (Configuración): each user only ever sees their own.
-- ---------------------------------------------------------------------------
create table if not exists public.in_user_preferences (
    auth_user_id uuid primary key default auth.uid() references auth.users(id) on delete cascade,
    theme text not null default 'system' check (theme in ('light', 'dark', 'system')),
    preferences jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now()
);
alter table public.in_user_preferences enable row level security;
create policy in_user_preferences_own on public.in_user_preferences for all to authenticated
    using (auth_user_id = (select auth.uid()) and (select public.in_is_member()))
    with check (auth_user_id = (select auth.uid()) and (select public.in_is_member()));

-- ---------------------------------------------------------------------------
-- 5. Audit log: append-only record of who did what. Never holds secrets
--    (the backend strips them before writing). Members write their own
--    events; only admins read. Nobody updates or deletes (trigger below also
--    stops roles that bypass RLS).
-- ---------------------------------------------------------------------------
create table if not exists public.in_audit_log (
    id uuid primary key default gen_random_uuid(),
    occurred_at timestamptz not null default now(),
    actor_auth_id uuid,
    actor_member_id text,
    actor_email text,
    action text not null check (action ~ '^[a-z_]+(\.[a-z_]+)+$'),
    module text not null check (length(module) <= 64),
    result text not null check (result in ('success', 'failure', 'denied', 'error')),
    operation_id text,
    resource_type text,
    resource_id text,
    context jsonb not null default '{}'::jsonb,
    ip text,
    user_agent text
);
create index if not exists in_audit_log_occurred_at_idx on public.in_audit_log (occurred_at desc);
create index if not exists in_audit_log_action_idx on public.in_audit_log (action);
create index if not exists in_audit_log_actor_idx on public.in_audit_log (actor_auth_id);
create index if not exists in_audit_log_module_idx on public.in_audit_log (module);
alter table public.in_audit_log enable row level security;
create policy in_audit_log_member_insert on public.in_audit_log for insert to authenticated
    with check ((select public.in_is_member()) and actor_auth_id = (select auth.uid()));
create policy in_audit_log_admin_read on public.in_audit_log for select to authenticated using ((select public.in_is_admin()));

create or replace function public.in_audit_log_append_only()
returns trigger language plpgsql set search_path = '' as $$
begin
    raise exception 'in_audit_log es de solo inserción';
end
$$;
drop trigger if exists in_audit_log_no_update_delete on public.in_audit_log;
create trigger in_audit_log_no_update_delete before update or delete on public.in_audit_log
    for each row execute function public.in_audit_log_append_only();

-- Authentication failures happen BEFORE there is a session, so they cannot be
-- written under a member's identity. This narrow function accepts only these
-- actions, truncates every field and throttles itself.
create or replace function public.in_log_auth_event(
    p_action text, p_email text, p_reason text, p_ip text default null, p_user_agent text default null
) returns void language plpgsql security definer set search_path = '' as $$
begin
    if p_action not in ('auth.login_failed', 'auth.session_expired', 'auth.access_denied') then
        raise exception 'acción de autenticación no permitida';
    end if;
    if (select count(*) from public.in_audit_log
        where module = 'auth' and actor_auth_id is null and occurred_at > now() - interval '1 minute') >= 60 then
        return;  -- throttle: a flood of reports cannot fill the log
    end if;
    insert into public.in_audit_log (action, module, result, actor_email, context, ip, user_agent)
    values (
        p_action,
        'auth',
        case when p_action = 'auth.access_denied' then 'denied' else 'failure' end,
        left(lower(nullif(trim(p_email), '')), 254),
        jsonb_build_object('reason', left(coalesce(p_reason, ''), 200), 'reported_by', 'client'),
        left(p_ip, 64),
        left(p_user_agent, 300)
    );
end
$$;
revoke execute on function public.in_log_auth_event(text, text, text, text, text) from public;
grant execute on function public.in_log_auth_event(text, text, text, text, text) to anon, authenticated;

-- ---------------------------------------------------------------------------
-- 6. Observability: operational events (source connections, agent runs,
--    report generation, errors). No secrets, no payloads. Admins read.
-- ---------------------------------------------------------------------------
create table if not exists public.in_ops_events (
    id uuid primary key default gen_random_uuid(),
    occurred_at timestamptz not null default now(),
    level text not null check (level in ('INFO', 'WARNING', 'ERROR')),
    category text not null check (category in ('request', 'auth', 'source', 'agent', 'report', 'config', 'system')),
    event text not null check (length(event) <= 100),
    message text not null check (length(message) <= 2000),
    status text,
    duration_ms integer,
    operation_id text,
    actor_auth_id uuid,
    context jsonb not null default '{}'::jsonb
);
create index if not exists in_ops_events_occurred_at_idx on public.in_ops_events (occurred_at desc);
create index if not exists in_ops_events_level_idx on public.in_ops_events (level);
create index if not exists in_ops_events_category_idx on public.in_ops_events (category);
alter table public.in_ops_events enable row level security;
create policy in_ops_events_member_insert on public.in_ops_events for insert to authenticated
    with check ((select public.in_is_member()) and actor_auth_id = (select auth.uid()));
create policy in_ops_events_admin_read on public.in_ops_events for select to authenticated using ((select public.in_is_admin()));
