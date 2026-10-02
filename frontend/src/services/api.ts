import { fetchEventSource } from "@microsoft/fetch-event-source";
import { supabase } from "../lib/supabase";
import type {
  AgentExecution,
  AuditFilters,
  AuditPage,
  Company,
  ConversationSummary,
  GenerateReportRequest,
  Me,
  MessageOut,
  ObservabilitySummary,
  OpsEvent,
  PreferencesPayload,
  RecentReport,
  ReportInfo,
  ReportTemplate,
  RequestRecord,
  RequestStats,
  SaveSourceSettingsResult,
  SourceConnectionTest,
  SourceSettings,
  SourceSettingsInput,
  SourceStatus,
  StreamEvent,
} from "../types";

const BASE_URL = "/api";

/** An API failure with the backend's machine-readable code (e.g. "session_expired"). */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

let onAuthFailure: ((code: string | null) => void) | null = null;

/** Called when the backend rejects the session (401): the auth store signs out. */
export function setAuthFailureHandler(handler: ((code: string | null) => void) | null) {
  onAuthFailure = handler;
}

async function authHeaders(): Promise<Record<string, string>> {
  // getSession() returns a refreshed session when the access token is about to expire.
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function toApiError(res: Response): Promise<ApiError> {
  let message = `Error ${res.status}`;
  let code: string | null = null;
  try {
    const body = (await res.json()) as { detail?: unknown };
    const detail = body.detail;
    if (typeof detail === "string") message = detail;
    else if (detail && typeof detail === "object" && "message" in detail) {
      message = String((detail as { message: unknown }).message);
      code = "code" in detail ? String((detail as { code: unknown }).code) : null;
    } else if (Array.isArray(detail)) message = "Revisa los datos ingresados.";
  } catch {
    // not JSON: keep the status-based message
  }
  if (res.status === 401) onAuthFailure?.(code);
  if (res.status >= 500 && message.startsWith("Error ")) {
    message = "El servidor tuvo un problema. Intenta de nuevo en unos segundos.";
  }
  return new ApiError(res.status, message, code);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(await authHeaders()), ...(init.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, "No hay conexión con el servidor. Revisa tu red e intenta de nuevo.");
  }
  if (!res.ok) throw await toApiError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const json = (body: unknown) => JSON.stringify(body);

// ---- identity -----------------------------------------------------------------------

export const getMe = () => request<Me>("/me");
export const getPreferences = () => request<PreferencesPayload>("/me/preferences");
export const savePreferences = (payload: PreferencesPayload) =>
  request<PreferencesPayload>("/me/preferences", { method: "PUT", body: json(payload) });
export const reportSessionEvent = (event: "login" | "logout") =>
  request<void>("/me/session-events", { method: "POST", body: json({ event }) });

/** No session exists yet when a sign-in fails: this endpoint is public and rate-limited. */
export async function reportAuthFailure(action: "login_failed" | "session_expired", email: string, reason: string) {
  try {
    await fetch(`${BASE_URL}/auth/events`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: json({ action, email: email || null, reason: reason.slice(0, 200) }),
    });
  } catch {
    // best effort: auditing a failure must never block the login screen
  }
}

// ---- conversations & reports -----------------------------------------------------

export const createConversation = (title?: string) =>
  request<ConversationSummary>("/conversations", { method: "POST", body: json({ title: title ?? null }) });
export const listConversations = () => request<ConversationSummary[]>("/conversations");
export const getConversation = (id: string) =>
  request<ConversationSummary & { messages: MessageOut[]; report: ReportInfo | null }>(`/conversations/${id}`);
export const renameConversation = (id: string, title: string) =>
  request<ConversationSummary>(`/conversations/${id}`, { method: "PATCH", body: json({ title }) });
export const setConversationPinned = (id: string, isPinned: boolean) =>
  request<ConversationSummary>(`/conversations/${id}/pin`, { method: "PATCH", body: json({ is_pinned: isPinned }) });
export const deleteConversation = (id: string) => request<void>(`/conversations/${id}`, { method: "DELETE" });

export const listRecentReports = (limit = 20) => request<RecentReport[]>(`/reports?limit=${limit}`);
export const listCompanies = () => request<Company[]>("/companies");
export const listReportTemplates = () => request<ReportTemplate[]>("/report-templates");

async function downloadBlob(path: string, filename: string): Promise<void> {
  const res = await fetch(`${BASE_URL}${path}`, { headers: await authHeaders() });
  if (!res.ok) throw await toApiError(res);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export const downloadReport = (reportId: string, filename: string) =>
  downloadBlob(`/reports/${reportId}/download`, filename);

async function stream(path: string, body: unknown, onEvent: (event: StreamEvent) => void, signal?: AbortSignal) {
  const headers = { "Content-Type": "application/json", ...(await authHeaders()) };
  await fetchEventSource(`${BASE_URL}${path}`, {
    method: "POST",
    headers,
    body: json(body),
    signal,
    // One-shot POST that generates and persists a report server-side -- NOT a
    // subscription to reopen. Without this the library aborts the fetch when the tab
    // is backgrounded and silently re-POSTs it, duplicating the whole generation.
    openWhenHidden: true,
    async onopen(res) {
      if (!res.ok) throw await toApiError(res);
    },
    onmessage(ev) {
      if (!ev.data) return;
      onEvent(JSON.parse(ev.data) as StreamEvent);
    },
    onerror(err) {
      throw err;
    },
  });
}

export const generateReport = (req: GenerateReportRequest, onEvent: (e: StreamEvent) => void, signal?: AbortSignal) =>
  stream("/reports/generate", req, onEvent, signal);
export const sendMessage = (id: string, content: string, onEvent: (e: StreamEvent) => void, signal?: AbortSignal) =>
  stream(`/conversations/${id}/messages`, { content }, onEvent, signal);

// ---- data source -------------------------------------------------------------------

export const getSourceStatus = () => request<SourceStatus>("/source-settings/status");
export const getSourceSettings = () => request<SourceSettings>("/source-settings");
export const testSourceSettings = (input: SourceSettingsInput) =>
  request<SourceConnectionTest>("/source-settings/test", { method: "POST", body: json(input) });
export const saveSourceSettings = (input: SourceSettingsInput, opts: { skipTest?: boolean; revision?: number } = {}) =>
  request<SaveSourceSettingsResult>("/source-settings", {
    method: "PUT",
    body: json({ ...input, skip_connection_test: !!opts.skipTest, expected_revision: opts.revision ?? null }),
  });

// ---- audit & observability -------------------------------------------------------------

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const listAudit = (filters: AuditFilters, limit: number, offset: number) =>
  request<AuditPage>(`/audit${query({ ...filters, limit, offset })}`);
export const exportAudit = (filters: AuditFilters) =>
  downloadBlob(`/audit/export.csv${query({ ...filters })}`, `auditoria-${new Date().toISOString().slice(0, 10)}.csv`);

export const getObservabilitySummary = () => request<ObservabilitySummary>("/observability/summary");
export const listOpsEvents = (params: { level?: string; category?: string; q?: string; hours?: number; limit?: number }) =>
  request<{ items: OpsEvent[]; total: number | null }>(`/observability/events${query(params)}`);
export const listRequests = (limit = 100) =>
  request<{ items: RequestRecord[]; stats: RequestStats }>(`/observability/requests?limit=${limit}`);
export const listExecutions = (limit = 50) => request<{ items: AgentExecution[] }>(`/observability/executions?limit=${limit}`);
