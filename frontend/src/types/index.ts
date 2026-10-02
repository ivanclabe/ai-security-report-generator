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
