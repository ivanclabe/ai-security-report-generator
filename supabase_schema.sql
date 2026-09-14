-- ============================================================================
-- supabase_schema.sql — Fase 2: modelo de datos objetivo
--
-- NO EJECUTAR TODAVÍA. Entregable de diseño para revisión (ver DATA_MODEL.md).
-- Cuando se apruebe, aplicar tal cual desde el backend/agente con acceso a
-- Supabase -- es 100% aditivo e idempotente:
--   * Solo CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS.
--   * Ninguna sentencia DROP, RENAME, ni ALTER COLUMN TYPE.
--   * No modifica ni borra ninguna fila de las tablas in_* ya existentes
--     (in_conversations, in_messages, in_reports, in_report_versions).
--   * Las columnas nuevas en tablas existentes son NULL-ables o tienen DEFAULT
--     -- ninguna tabla con filas existentes recibe una columna NOT NULL sin
--     default.
--
-- Orden de aplicación (ya respetado por este archivo): entidades sin
-- dependencias -> extensiones a tablas existentes -> entidades dependientes
-- de nivel 2 -> entidades dependientes de nivel 3.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- Nivel 0: entidades sin dependencias
-- ----------------------------------------------------------------------------

create table if not exists in_companies (
    id text primary key,                       -- slug, ej. "thomas-tgs-tps" (igual convención que _slugify() en excel.py)
    name text not null,
    industry text,
    country text,
    created_at timestamptz not null default now()
);

create table if not exists in_users (
    id text primary key,
    username text not null unique,
    display_name text,
    role text not null default 'operator',      -- 'operator' | 'admin' (sin aplicación real hasta Fase 9)
    created_at timestamptz not null default now()
);

-- Login único ya existente (master/123456) representado como una fila --
-- no reemplaza el mecanismo de auth actual (JWT hardcodeado), solo le da
-- una fila a la que referenciar desde created_by/triggered_by/imported_by.
insert into in_users (id, username, display_name, role)
values ('user-master', 'master', 'Operador', 'admin')
on conflict (id) do nothing;

create table if not exists in_report_templates (
    id text primary key,
    key text not null unique,                   -- ej. "csoc_mensual"
    name text not null,
    description text,
    is_active boolean not null default true,
    created_at timestamptz not null default now()
);

-- La única plantilla activa hoy (el esqueleto de 11 secciones ya implementado
-- en generate_report_spec.py) -- registrarla no cambia su comportamiento,
-- solo le da una fila con la que in_report_versions.template_id puede vincularse.
insert into in_report_templates (id, key, name, description, is_active)
values (
    'tmpl-csoc-mensual',
    'csoc_mensual',
    'Informe de Gestión CSOC Mensual',
    'Plantilla de 11 secciones que replica el informe recurrente real del cliente.',
    true
)
on conflict (id) do nothing;


-- ----------------------------------------------------------------------------
-- Nivel 1: extensiones a tablas existentes (aditivas, columnas nullable/default)
-- ----------------------------------------------------------------------------

alter table in_conversations
    add column if not exists company_id text references in_companies(id),
    add column if not exists created_by text references in_users(id);

alter table in_reports
    add column if not exists company_id text references in_companies(id);
    -- La columna "company" (texto libre) se conserva sin cambios -- ver
    -- DATA_MODEL.md §4. No se agrega FK NOT NULL para no romper filas existentes.

alter table in_report_versions
    add column if not exists template_id text references in_report_templates(id),
    add column if not exists format text not null default 'docx'
        check (format in ('docx', 'pdf'));


-- ----------------------------------------------------------------------------
-- Nivel 2: entidades que dependen de companies/users
-- ----------------------------------------------------------------------------

create table if not exists in_data_sources (
    id text primary key,
    company_id text not null references in_companies(id) on delete cascade,
    source_type text not null check (source_type in ('excel', 'api', 'mock')),
    name text not null,                          -- etiqueta humana, ej. "Excel mensual TGS-TPS"
    config jsonb not null default '{}'::jsonb,    -- NUNCA secretos en texto plano -- ver DATA_MODEL.md §7
    is_active boolean not null default true,
    created_at timestamptz not null default now()
);

create index if not exists in_data_sources_company_id_idx on in_data_sources(company_id);


-- ----------------------------------------------------------------------------
-- Nivel 3: entidades que dependen de data_sources
-- ----------------------------------------------------------------------------

create table if not exists in_data_imports (
    id text primary key,
    data_source_id text not null references in_data_sources(id) on delete cascade,
    company_id text not null references in_companies(id),
    source_file_ref text,                         -- ruta en Supabase Storage (bucket "data-sources") o nombre de archivo original
    file_hash text,                                -- sha256, para detectar reimportaciones idénticas
    status text not null check (status in ('success', 'partial', 'failed')),
    row_count integer,
    warning_count integer,
    warnings jsonb not null default '[]'::jsonb,   -- espejo de ExcelIngestionResult.warnings
    imported_by text references in_users(id),
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz not null default now()
);

create index if not exists in_data_imports_company_id_idx on in_data_imports(company_id);
create index if not exists in_data_imports_data_source_id_idx on in_data_imports(data_source_id);


-- ----------------------------------------------------------------------------
-- Nivel 4: entidades que dependen de data_imports / conversations / reports
-- ----------------------------------------------------------------------------

create table if not exists in_security_alerts (
    id text primary key,
    data_import_id text not null references in_data_imports(id) on delete cascade,
    company_id text not null references in_companies(id),
    alarm_number text not null,
    original_id text,
    alert_type text,
    category text,
    severity_score integer,
    risk_level text,
    is_voided boolean not null default false,
    event_timestamp timestamptz,
    status text,
    mitre_tactic_id text,
    description text,
    raw_record jsonb not null default '{}'::jsonb,        -- fila original del Excel/API, sin normalizar
    normalized_record jsonb not null default '{}'::jsonb,  -- dump completo de NormalizedSecurityAlert (forward-compat)
    created_at timestamptz not null default now()
);

create index if not exists in_security_alerts_company_period_idx
    on in_security_alerts(company_id, event_timestamp);
create index if not exists in_security_alerts_company_risk_idx
    on in_security_alerts(company_id, risk_level);
create index if not exists in_security_alerts_alarm_number_idx
    on in_security_alerts(alarm_number);
create index if not exists in_security_alerts_data_import_id_idx
    on in_security_alerts(data_import_id);

create table if not exists in_agent_executions (
    id text primary key,
    conversation_id text references in_conversations(id) on delete set null,
    report_id text references in_reports(id) on delete set null,
    report_version_id text references in_report_versions(id) on delete set null,
    company_id text references in_companies(id),
    mode text not null check (mode in ('conversational', 'deterministic')),
    triggered_by text references in_users(id),
    request_params jsonb not null default '{}'::jsonb,   -- el ReportRequest usado
    data_import_ids jsonb not null default '[]'::jsonb,  -- qué importación(es) alimentaron esta ejecución
    model text,
    status text not null check (status in ('running', 'ready', 'awaiting_user_input', 'error')),
    error_messages jsonb not null default '[]'::jsonb,
    started_at timestamptz not null default now(),
    completed_at timestamptz,
    duration_ms integer
);

create index if not exists in_agent_executions_company_id_idx on in_agent_executions(company_id);
create index if not exists in_agent_executions_conversation_id_idx on in_agent_executions(conversation_id);
create index if not exists in_agent_executions_status_idx on in_agent_executions(status);

-- Opcional para el MVP de la Fase 4 (ver DATA_MODEL.md §1) -- se crea ahora
-- para no rediseñar el esquema más adelante, pero poblarla no es requisito
-- de la primera migración de código.
create table if not exists in_report_evidence (
    id text primary key,
    report_version_id text not null references in_report_versions(id) on delete cascade,
    alert_id text not null references in_security_alerts(id) on delete cascade,
    section_number text,                          -- ej. "6.4", coincide con Section.number/Subsection.number
    role text                                      -- ej. 'significant_alert' | 'recommendation_evidence'
);

create index if not exists in_report_evidence_report_version_id_idx
    on in_report_evidence(report_version_id);
create index if not exists in_report_evidence_alert_id_idx
    on in_report_evidence(alert_id);


-- ----------------------------------------------------------------------------
-- Row Level Security -- mismo patrón que las tablas in_* existentes:
-- acceso completo solo para el rol "anon", usado exclusivamente por el
-- backend (la clave nunca se expone al frontend). Ver DATA_MODEL.md §7 sobre
-- por qué el aislamiento real por usuario/tenant queda para la Fase 9.
-- ----------------------------------------------------------------------------

alter table in_companies enable row level security;
alter table in_users enable row level security;
alter table in_report_templates enable row level security;
alter table in_data_sources enable row level security;
alter table in_data_imports enable row level security;
alter table in_security_alerts enable row level security;
alter table in_agent_executions enable row level security;
alter table in_report_evidence enable row level security;

create policy "in_companies_anon_all" on in_companies for all to anon using (true) with check (true);
create policy "in_users_anon_all" on in_users for all to anon using (true) with check (true);
create policy "in_report_templates_anon_all" on in_report_templates for all to anon using (true) with check (true);
create policy "in_data_sources_anon_all" on in_data_sources for all to anon using (true) with check (true);
create policy "in_data_imports_anon_all" on in_data_imports for all to anon using (true) with check (true);
create policy "in_security_alerts_anon_all" on in_security_alerts for all to anon using (true) with check (true);
create policy "in_agent_executions_anon_all" on in_agent_executions for all to anon using (true) with check (true);
create policy "in_report_evidence_anon_all" on in_report_evidence for all to anon using (true) with check (true);


-- ----------------------------------------------------------------------------
-- Supabase Storage -- buckets para documentos generados y archivos fuente.
-- No aplicable como SQL puro en todos los proyectos Supabase (según versión,
-- puede requerir el dashboard o la API de Storage) -- se documenta la
-- intención aquí; la creación real de los buckets se ejecuta en la Fase 4
-- junto con el código que los usa, no como parte de este script de esquema.
--
--   bucket "reports"       (privado) -- guarda los .docx/.pdf generados
--   bucket "data-sources"  (privado) -- guarda el Excel/JSON original de cada importación
-- ----------------------------------------------------------------------------
