import { fetchEventSource } from "@microsoft/fetch-event-source";
import type {
  Company,
  ConversationSummary,
  GenerateReportRequest,
  LoginResponse,
  MessageOut,
  ReportInfo,
  ReportTemplate,
  SaveSourceSettingsResult,
  SourceConnectionTest,
  SourceSettings,
  SourceSettingsInput,
  StreamEvent,
} from "../types";

const BASE_URL = "/api";
const TOKEN_STORAGE_KEY = "ai_report_gen_token";

let authToken: string | null = readStoredToken();
let onUnauthorized: (() => void) | null = null;

function readStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setAuthToken(token: string | null) {
  authToken = token;
  try {
    if (token) localStorage.setItem(TOKEN_STORAGE_KEY, token);
    else localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    // localStorage unavailable (private mode, etc.) -- token still works for this session
  }
}

export function getAuthToken(): string | null {
  return authToken;
}

export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

function authHeaders(): Record<string, string> {
  return authToken ? { Authorization: `Bearer ${authToken}` } : {};
}

async function json<T>(res: Response): Promise<T> {
  if (res.status === 401) {
    setAuthToken(null);
    onUnauthorized?.();
  }
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`Request failed (${res.status}): ${text}`);
  }
  return res.json() as Promise<T>;
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  const res = await fetch(`${BASE_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  return json(res);
}

export async function createConversation(title?: string): Promise<ConversationSummary> {
  const res = await fetch(`${BASE_URL}/conversations`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ title: title ?? null }),
  });
  return json(res);
}

export async function listConversations(): Promise<ConversationSummary[]> {
  const res = await fetch(`${BASE_URL}/conversations`, { headers: authHeaders() });
  return json(res);
}

export async function getConversation(
  conversationId: string,
): Promise<ConversationSummary & { messages: MessageOut[]; report: ReportInfo | null }> {
  const res = await fetch(`${BASE_URL}/conversations/${conversationId}`, { headers: authHeaders() });
  return json(res);
}

export async function renameConversation(
  conversationId: string,
  title: string,
): Promise<ConversationSummary> {
  const res = await fetch(`${BASE_URL}/conversations/${conversationId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ title }),
  });
  return json(res);
}

export async function setConversationPinned(
  conversationId: string,
  isPinned: boolean,
): Promise<ConversationSummary> {
  const res = await fetch(`${BASE_URL}/conversations/${conversationId}/pin`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ is_pinned: isPinned }),
  });
  return json(res);
}

export async function deleteConversation(conversationId: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/conversations/${conversationId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (res.status === 401) {
    setAuthToken(null);
    onUnauthorized?.();
  }
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`Request failed (${res.status}): ${text}`);
  }
}

export async function downloadReport(reportId: string, filename: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/reports/${reportId}/download`, { headers: authHeaders() });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`Request failed (${res.status}): ${text}`);
  }
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

export async function listCompanies(): Promise<Company[]> {
  const res = await fetch(`${BASE_URL}/companies`, { headers: authHeaders() });
  return json(res);
}

export async function listReportTemplates(): Promise<ReportTemplate[]> {
  const res = await fetch(`${BASE_URL}/report-templates`, { headers: authHeaders() });
  return json(res);
}

/** Like json(), but surfaces the API's `detail` message (e.g. why an address is invalid). */
async function jsonWithDetail<T>(res: Response): Promise<T> {
  if (res.status === 401) {
    setAuthToken(null);
    onUnauthorized?.();
  }
  if (!res.ok) {
    let message = `Error ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      // not JSON -- keep the status-based message
    }
    throw new Error(message);
  }
  return res.json() as Promise<T>;
}

export async function getSourceSettings(): Promise<SourceSettings> {
  const res = await fetch(`${BASE_URL}/source-settings`, { headers: authHeaders() });
  return jsonWithDetail(res);
}

export async function testSourceSettings(input: SourceSettingsInput): Promise<SourceConnectionTest> {
  const res = await fetch(`${BASE_URL}/source-settings/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(input),
  });
  return jsonWithDetail(res);
}

export async function saveSourceSettings(
  input: SourceSettingsInput,
  skipConnectionTest = false,
): Promise<SaveSourceSettingsResult> {
  const res = await fetch(`${BASE_URL}/source-settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ ...input, skip_connection_test: skipConnectionTest }),
  });
  return jsonWithDetail(res);
}

export async function generateReport(
  request: GenerateReportRequest,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  await fetchEventSource(`${BASE_URL}/reports/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(request),
    signal,
    // This is a one-shot POST that generates and persists a report server-side --
    // NOT a subscription to reopen. Without this, the library aborts the fetch
    // whenever the tab is backgrounded and silently reconnects (re-POSTs the same
    // body) when it becomes visible again, duplicating the whole generation
    // (found live: a PDF request takes long enough for this to actually happen).
    openWhenHidden: true,
    async onopen(res) {
      if (res.status === 401) {
        setAuthToken(null);
        onUnauthorized?.();
      }
      if (!res.ok) {
        throw new Error(`Failed to start stream (${res.status})`);
      }
    },
    onmessage(ev) {
      if (!ev.data) return;
      const parsed = JSON.parse(ev.data) as StreamEvent;
      onEvent(parsed);
    },
    onerror(err) {
      throw err;
    },
  });
}

export async function sendMessage(
  conversationId: string,
  content: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  await fetchEventSource(`${BASE_URL}/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ content }),
    signal,
    // See the same option in generateReport() -- without it, backgrounding the tab
    // during a slow generation (e.g. PDF) aborts and silently re-POSTs the message.
    openWhenHidden: true,
    async onopen(res) {
      if (res.status === 401) {
        setAuthToken(null);
        onUnauthorized?.();
      }
      if (!res.ok) {
        throw new Error(`Failed to start stream (${res.status})`);
      }
    },
    onmessage(ev) {
      if (!ev.data) return;
      const parsed = JSON.parse(ev.data) as StreamEvent;
      onEvent(parsed);
    },
    onerror(err) {
      throw err;
    },
  });
}
