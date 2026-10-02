import { PROVIDER_LABELS } from "../../store/useLLMStore";
import type { LLMRunInfo } from "../../types";
import { IconCpu } from "../icons";
import { Badge } from "../ui/Badge";

/** Which provider/model is (or was) working on this report -- visible while it runs. */
export function LLMRunStatus({ info, status }: { info: LLMRunInfo | null; status?: string | null }) {
  if (!info) return null;
  const isAuto = info.requested === "auto";
  return (
    <dl
      className="grid grid-cols-2 gap-x-6 gap-y-2 rounded-lg border border-line bg-surface-2/60 px-4 py-3 text-xs sm:grid-cols-4"
      aria-live="polite"
    >
      <div>
        <dt className="text-fg-subtle">Proveedor</dt>
        <dd className="mt-0.5 flex items-center gap-1.5 font-semibold text-fg">
          <IconCpu className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
          {isAuto ? "Auto" : info.provider_label}
        </dd>
      </div>
      {isAuto && (
        <div>
          <dt className="text-fg-subtle">Proveedor activo</dt>
          <dd className="mt-0.5 font-semibold text-fg">{info.provider_label}</dd>
        </div>
      )}
      <div className={isAuto ? "" : "sm:col-span-2"}>
        <dt className="text-fg-subtle">Modelo</dt>
        <dd className="mt-0.5 truncate font-mono text-fg" title={info.model}>
          {info.model}
        </dd>
      </div>
      {isAuto && (
        <div>
          <dt className="text-fg-subtle">Fallback</dt>
          <dd className="mt-0.5 text-fg">{info.fallbacks.length ? info.fallbacks.map((f) => f.label.split(" · ")[0]).join(" → ") : "—"}</dd>
        </div>
      )}
      {status && (
        <div className="col-span-2 sm:col-span-4">
          <dt className="sr-only">Estado</dt>
          <dd className="text-fg-muted">{status}</dd>
        </div>
      )}
      {info.last_fallback && (
        <div className="col-span-2 sm:col-span-4">
          <Badge tone="warning" dot>
            Cambio de proveedor: {PROVIDER_LABELS[info.last_fallback.from] ?? info.last_fallback.from} →{" "}
            {PROVIDER_LABELS[info.last_fallback.to] ?? info.last_fallback.to} · motivo: {info.last_fallback.reason_label}
          </Badge>
        </div>
      )}
    </dl>
  );
}
