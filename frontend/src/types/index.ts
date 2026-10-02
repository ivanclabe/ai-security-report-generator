export interface ConversationSummary {
  id: string;
  title: string | null;
  is_pinned: boolean;
  created_at: string;
}

export interface LoginResponse {
  access_token: string;
  username: string;
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

export interface ProgressEvent {
  event: "progress";
  node: string;
  message: string;
}

export interface ResultEvent {
  event: "result";
  status: "ready" | "awaiting_user_input" | "error" | "answered" | string;
  message: string;
  errors: string[];
  report: ReportInfo | null;
  conversation_id?: string;
}

export type StreamEvent = ProgressEvent | ResultEvent;

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  report?: ReportInfo | null;
  isError?: boolean;
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
}

/** Configuración > Fuente de datos. The password is write-only: never returned by the API. */
export interface SourceSettings {
  base_url: string;
  username: string;
  password_set: boolean;
  uses_https: boolean;
  origin: "app" | "env";
  updated_at: string | null;
  updated_by: string | null;
  provider_active: boolean;
}

export interface SourceSettingsInput {
  base_url: string;
  username: string;
  /** Empty = keep the current password. */
  password?: string;
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
