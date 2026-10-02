export interface ConversationSummary {
  id: string;
  title: string | null;
  is_pinned: boolean;
  created_at: string;
}

export interface MessageOut {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface ReportInfo {
  report_id: string;
  version: number;
  title: string | null;
  section_count: number;
  objective?: string | null;
  format?: string;
}

export interface RecentReport {
  report_id: string;
  conversation_id: string;
  company: string | null;
  title: string | null;
  version: number;
  format: string;
  section_count: number;
  created_at: string;
}

export interface ProgressEvent {
  event: "progress";
  node: string;
  message: string;
  conversation_id?: string;
}

/** Machine-readable failure reasons the UI can act on (e.g. "go configure the source"). */
export type ErrorCode = "source_not_configured" | "source_error" | "llm_unavailable" | null;

export interface ResultEvent {
  event: "result";
  status: "ready" | "awaiting_user_input" | "error" | "answered" | string;
  message: string;
  errors: string[];
  report: ReportInfo | null;
  conversation_id?: string;
  error_code?: ErrorCode;
  llm?: LLMRunInfo;
}

export type StreamEvent = ProgressEvent | ResultEvent | LLMEvent;

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  report?: ReportInfo | null;
  isError?: boolean;
  errorCode?: ErrorCode;
  llm?: LLMRunInfo | null;
}

export interface Company {
  id: string;
  name: string;
  logo_key?: string | null;
  consecutivo?: string | null;
}

export interface ReportTemplate {
  key: string;
  name: string;
  description: string | null;
}

export interface GenerateReportRequest {
  company: string;
  start_date: string;
  end_date: string;
  report_type?: string;
  audience?: string;
  focus_categories?: string[];
  risk_level_filter?: string[];
  format?: string;
  llm?: LLMSelection;
}

// ---- identity & preferences ------------------------------------------------------

export interface Me {
  email: string | null;
  display_name: string | null;
  role: "admin" | "operator" | string;
  is_admin: boolean;
}

export type ThemePreference = "light" | "dark" | "system";

export interface UserPreferences {
  default_format: "docx" | "pdf";
  default_audience: string;
  start_page: "/" | "/informes/nuevo" | "/asistente";
  density: "comfortable" | "compact";
  reduce_motion: boolean;
  llm_provider?: LLMProvider | null;
  llm_model?: string | null;
}

export interface PreferencesPayload {
  theme: ThemePreference;
  preferences: UserPreferences;
  updated_at?: string | null;
}

// ---- data source -----------------------------------------------------------------

export interface SourceStatus {
  configured: boolean;
  missing: string[];
  host: string | null;
  uses_https: boolean;
  origin: "app" | "env" | string;
  provider_active: boolean;
}

export interface SourceSettings {
  scheme: "http" | "https";
  host: string;
  base_path: string;
  alarms_path: string;
  notifications_path: string;
  alarms_url: string;
  notifications_url: string;
  username: string;
  password_set: boolean;
  verify_tls: boolean;
  timeout_seconds: number;
  alarms_limit: number;
  reconcile_indicators: boolean;
  origin: "app" | "env" | string;
  revision: number;
  updated_at: string | null;
  updated_by: string | null;
  provider_active: boolean;
  encryption_ready: boolean;
}

export interface SourceSettingsInput {
  scheme: "http" | "https";
  host: string;
  base_path: string;
  alarms_path: string;
  notifications_path: string;
  username: string;
  /** Empty = keep the stored password (the API never returns it). */
  password?: string;
  verify_tls: boolean;
  timeout_seconds: number;
  alarms_limit: number;
  reconcile_indicators: boolean;
}

export interface SourceConnectionTest {
  ok: boolean;
  message: string;
  login_method: string | null;
  elapsed_seconds: number | null;
}

export interface SaveSourceSettingsResult {
  saved: boolean;
  test: SourceConnectionTest | null;
  settings: SourceSettings;
}

// ---- audit & observability ---------------------------------------------------------

export interface AuditEntry {
  id: string;
  occurred_at: string;
  actor_email: string | null;
  action: string;
  module: string;
  result: "success" | "failure" | "denied" | "error" | string;
  operation_id: string | null;
  resource_type: string | null;
  resource_id: string | null;
  context: Record<string, unknown>;
  ip: string | null;
  user_agent: string | null;
}

export interface AuditPage {
  items: AuditEntry[];
  total: number | null;
  limit: number;
  offset: number;
  modules: string[];
}

export interface AuditFilters {
  q?: string;
  module?: string;
  action?: string;
  result?: string;
  date_from?: string;
  date_to?: string;
}

export type OpsLevel = "INFO" | "WARNING" | "ERROR";

export interface OpsEvent {
  id?: string;
  occurred_at: string;
  level: OpsLevel;
  category: string;
  event: string;
  message: string;
  status: string | null;
  duration_ms: number | null;
  operation_id?: string | null;
  context?: Record<string, unknown>;
}

export interface RequestRecord {
  occurred_at: string;
  method: string;
  route: string;
  status: number;
  duration_ms: number;
  request_id: string | null;
  actor_email: string | null;
}

export interface RequestStats {
  window_seconds: number;
  total: number;
  server_errors: number;
  auth_failures: number;
  avg_duration_ms: number | null;
  p95_duration_ms: number | null;
}

export interface ObservabilitySummary {
  generated_at: string;
  process: { started_at: string; uptime_seconds: number; version: string | null };
  requests_last_hour: RequestStats;
  events_24h: { total: number; by_level: Record<string, number>; by_category: Record<string, number> };
  source: {
    configured: boolean;
    missing: string[];
    host: string | null;
    uses_https: boolean;
    last_event: OpsEvent | null;
    last_error: OpsEvent | null;
  };
  agent_24h: {
    total: number;
    by_status: Record<string, number>;
    avg_duration_ms: number | null;
    max_duration_ms: number | null;
  };
  reports_24h: number;
}

export interface AgentExecution {
  id: string;
  mode: string;
  status: string;
  company_id: string | null;
  model: string | null;
  duration_ms: number | null;
  started_at: string;
  completed_at: string | null;
  error_count: number;
  estimated_cost_usd: number | null;
}

// ---- AI providers (LLM Provider Layer) -------------------------------------------------

export type LLMProvider = "auto" | "cloud" | "local" | "vllm";
export type LLMProviderKind = Exclude<LLMProvider, "auto">;

export interface LLMSelection {
  provider: LLMProvider;
  model?: string | null;
}

export interface LLMCatalogProvider {
  provider: LLMProviderKind;
  label: string;
  vendor_label: string;
  enabled: boolean;
  configured: boolean;
  problem: string | null;
  default_model: string;
  models: string[];
}

export interface LLMCatalog {
  selectable: LLMProvider[];
  providers: LLMCatalogProvider[];
  routing: {
    default_provider: LLMProvider;
    auto_order: LLMProviderKind[];
    auto_candidates: LLMProviderKind[];
    preflight_check: boolean;
    runtime_fallback: boolean;
  };
  default_selection: { provider: LLMProvider; model: string | null };
}

export type LLMHealthStatus =
  | "available"
  | "unavailable"
  | "auth_error"
  | "timeout"
  | "model_unavailable"
  | "connection_error"
  | "server_error"
  | "rate_limited"
  | "not_configured"
  | "disabled";

export interface LLMHealth {
  provider: LLMProviderKind;
  status: LLMHealthStatus;
  label: string;
  ok: boolean;
  latency_ms: number | null;
  detail: string;
  model: string | null;
  models_count: number;
  checked_at: string;
  models?: string[];
}

export interface LLMParams {
  temperature: number | null;
  max_tokens: number | null;
  top_p: number | null;
  timeout_seconds: number;
  context_window: number | null;
  structured_output: "auto" | "json_schema" | "function_calling" | "json_mode";
}

export interface LLMProviderSettings {
  provider: LLMProviderKind;
  label: string;
  vendor: string;
  vendor_label: string;
  enabled: boolean;
  base_url: string;
  effective_base_url: string;
  api_key_set: boolean;
  api_key_hint: string | null;
  requires_api_key: boolean;
  default_model: string;
  manual_models: string[];
  discovered_models: string[];
  models: string[];
  discovery_enabled: boolean;
  params: LLMParams;
  revision: number;
  updated_at: string | null;
  origin: "app" | "env" | string;
}

export interface LLMProviderInput {
  vendor: string;
  enabled: boolean;
  base_url: string;
  api_key?: string;
  clear_api_key?: boolean;
  default_model: string;
  manual_models: string[];
  discovery_enabled: boolean;
  params: LLMParams;
}

export interface LLMRouting {
  default_provider: LLMProvider;
  auto_order: LLMProviderKind[];
  health_ttl_seconds: number;
  preflight_check: boolean;
  runtime_fallback: boolean;
  revision: number;
  updated_at: string | null;
  origin: string;
}

export interface LLMVendorOption {
  vendor: string;
  label: string;
  default_base_url: string;
  requires_api_key: boolean;
}

export interface LLMProvidersAdmin {
  providers: LLMProviderSettings[];
  routing: LLMRouting;
  vendors: Record<LLMProviderKind, LLMVendorOption[]>;
  encryption_ready: boolean;
}

/** What actually runs a report / chat turn (SSE "llm" events and the result). */
export interface LLMRunInfo {
  requested: LLMProvider;
  requested_label: string;
  provider: LLMProviderKind;
  provider_label: string;
  vendor: string;
  model: string;
  fallbacks: { provider: LLMProviderKind; model: string; label: string }[];
  switched: boolean;
  last_fallback: { from: string; to: string; reason: string; reason_label: string; stage: string } | null;
}

export interface LLMEvent extends LLMRunInfo {
  event: "llm";
  phase: "selected" | "fallback";
}

export interface EvaluationMetrics {
  extraction_accuracy: number;
  severity_accuracy: number;
  risk_identification: number;
  recommendation_quality: number;
  report_quality: number;
  consistency: number | null;
}

export interface EvaluationResult {
  provider: LLMProviderKind;
  requested_model: string | null;
  status: "completed" | "unavailable";
  model?: string;
  vendor?: string;
  metrics?: EvaluationMetrics;
  overall?: number;
  calls?: number;
  failed_calls?: number;
  avg_latency_ms?: number | null;
  input_tokens?: number;
  output_tokens?: number;
  errors?: string[];
  error_count?: number;
  validation_errors?: number;
  duration_ms?: number;
  error?: string;
}

export interface Evaluation {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  candidates: { provider: LLMProviderKind; model: string | null }[];
  repetitions: number;
  results: EvaluationResult[];
  summary: {
    baseline: { provider: string; model: string; overall: number } | null;
    ranking: { provider: string; model: string; overall: number }[];
    degradations: { provider: string; model: string; overall_delta: number; degraded: boolean; worse_metrics: Record<string, number> }[];
  } | null;
  error: string | null;
  created_at: string;
  completed_at: string | null;
}
