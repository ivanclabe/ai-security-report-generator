const dateTime = new Intl.DateTimeFormat("es-CO", { dateStyle: "medium", timeStyle: "short" });
const dateOnly = new Intl.DateTimeFormat("es-CO", { dateStyle: "medium" });
const relative = new Intl.RelativeTimeFormat("es", { numeric: "auto" });

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : dateTime.format(date);
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : dateOnly.format(date);
}

export function formatRelative(value: string | null | undefined): string {
  if (!value) return "—";
  const diff = (new Date(value).getTime() - Date.now()) / 1000;
  const abs = Math.abs(diff);
  if (abs < 60) return relative.format(Math.round(diff), "second");
  if (abs < 3600) return relative.format(Math.round(diff / 60), "minute");
  if (abs < 86400) return relative.format(Math.round(diff / 3600), "hour");
  return relative.format(Math.round(diff / 86400), "day");
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${ms} ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1).replace(".", ",")} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} min ${Math.round(seconds % 60)} s`;
}

export function formatUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return d ? `${d} d ${h} h` : h ? `${h} h ${m} min` : `${m} min`;
}

/** Human labels for audit actions (falls back to the technical name). */
export const ACTION_LABELS: Record<string, string> = {
  "auth.login": "Inicio de sesión",
  "auth.logout": "Cierre de sesión",
  "auth.login_failed": "Intento de inicio de sesión fallido",
  "auth.session_expired": "Sesión expirada",
  "auth.access_denied": "Acceso denegado (no es miembro)",
  "auth.admin_required": "Acceso denegado (requiere administrador)",
  "source.settings_updated": "Configuración de la fuente actualizada",
  "source.address_changed": "Cambio de IP / URL de la fuente",
  "source.connection_tested": "Prueba de conexión con la fuente",
  "report.generation_requested": "Solicitud de informe",
  "report.generated": "Informe generado",
  "report.generation_failed": "Fallo al generar informe",
  "report.generation_blocked": "Informe bloqueado (fuente sin configurar)",
  "report.downloaded": "Descarga de informe",
  "agent.message_sent": "Mensaje al asistente",
  "conversation.deleted": "Conversación eliminada",
  "settings.preferences_updated": "Preferencias actualizadas",
  "audit.exported": "Exportación de auditoría",
  "llm.provider_fallback": "Cambio automático de proveedor de IA",
  "llm.provider_error": "Error del proveedor de IA",
  "llm.provider_settings_updated": "Configuración de proveedor de IA actualizada",
  "llm.model_changed": "Cambio de modelo predeterminado",
  "llm.routing_updated": "Enrutamiento de IA actualizado",
  "llm.provider_tested": "Prueba de proveedor de IA",
  "llm.models_refreshed": "Actualización de modelos disponibles",
  "llm.evaluation_started": "Evaluación de IA iniciada",
  "llm.evaluation_completed": "Evaluación de IA completada",
};

export const MODULE_LABELS: Record<string, string> = {
  auth: "Autenticación",
  fuente_de_datos: "Fuente de datos",
  informes: "Informes",
  asistente: "Asistente",
  configuracion: "Configuración",
  auditoria: "Auditoría",
  ia: "Inteligencia artificial",
};

export const RESULT_LABELS: Record<string, { label: string; tone: "success" | "warning" | "danger" | "neutral" }> = {
  success: { label: "Éxito", tone: "success" },
  failure: { label: "Fallo", tone: "warning" },
  denied: { label: "Denegado", tone: "danger" },
  error: { label: "Error", tone: "danger" },
};

export const CATEGORY_LABELS: Record<string, string> = {
  request: "Solicitudes",
  auth: "Autenticación",
  source: "Fuente de datos",
  agent: "Asistente",
  report: "Informes",
  config: "Configuración",
  system: "Sistema",
  llm: "IA",
};

export const EXECUTION_STATUS: Record<string, { label: string; tone: "success" | "warning" | "danger" | "info" | "neutral" }> = {
  ready: { label: "Completado", tone: "success" },
  running: { label: "En curso", tone: "info" },
  awaiting_user_input: { label: "Esperando datos", tone: "warning" },
  error: { label: "Error", tone: "danger" },
};
