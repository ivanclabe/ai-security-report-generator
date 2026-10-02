import { formatDuration } from "../../lib/format";
import type { LLMHealth } from "../../types";
import { Badge, type Tone } from "../ui/Badge";
import { Spinner } from "../ui/Spinner";

const TONE: Record<string, Tone> = {
  available: "success",
  not_configured: "neutral",
  disabled: "neutral",
  model_unavailable: "warning",
  rate_limited: "warning",
  timeout: "danger",
  auth_error: "danger",
  connection_error: "danger",
  server_error: "danger",
  unavailable: "danger",
};

export function HealthBadge({ health }: { health: LLMHealth | "checking" | undefined }) {
  if (health === undefined) return <Badge tone="neutral">Sin comprobar</Badge>;
  if (health === "checking")
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-fg-subtle" role="status">
        <Spinner className="h-3 w-3" /> Comprobando…
      </span>
    );
  return (
    <span title={health.detail || undefined}>
      <Badge tone={TONE[health.status] ?? "neutral"} dot>
        {health.label}
        {health.ok && health.latency_ms != null ? ` · ${formatDuration(health.latency_ms)}` : ""}
      </Badge>
    </span>
  );
}
