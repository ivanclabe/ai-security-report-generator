import { useEffect, useId } from "react";
import { healthKey, PROVIDER_LABELS, useLLMStore } from "../../store/useLLMStore";
import type { LLMProvider, LLMProviderKind } from "../../types";
import { IconRefresh } from "../icons";
import { HealthBadge } from "./HealthBadge";

const OPTION_ORDER: LLMProvider[] = ["auto", "cloud", "vllm", "local"];

/**
 * AI Provider + Model. Models come from the provider (discovery) plus the manual list --
 * nothing hardcoded here. The health badge tells whether the choice can run right now.
 */
export function LLMSelector({ compact = false, disabled = false }: { compact?: boolean; disabled?: boolean }) {
  const catalog = useLLMStore((s) => s.catalog);
  const selection = useLLMStore((s) => s.selection);
  const health = useLLMStore((s) => s.health);
  const load = useLLMStore((s) => s.load);
  const select = useLLMStore((s) => s.select);
  const checkHealth = useLLMStore((s) => s.checkHealth);
  const providerId = useId();
  const modelId = useId();

  useEffect(() => {
    if (!catalog) load();
  }, [catalog, load]);

  const providerInfo = catalog?.providers.find((p) => p.provider === selection.provider);
  const models = providerInfo?.models ?? [];
  const model = selection.model || providerInfo?.default_model || "";
  const autoOrder = catalog?.routing.auto_candidates ?? [];
  const healthTarget: LLMProviderKind | undefined = selection.provider === "auto" ? autoOrder[0] : (selection.provider as LLMProviderKind);
  const healthTargetModel =
    selection.provider === "auto" ? catalog?.providers.find((p) => p.provider === autoOrder[0])?.default_model : model;
  const currentHealth = healthTarget ? health[healthKey(healthTarget, healthTargetModel)] : undefined;

  useEffect(() => {
    if (healthTarget && currentHealth === undefined) checkHealth(healthTarget, healthTargetModel);
  }, [healthTarget, healthTargetModel, currentHealth, checkHealth]);

  const selectClass = compact ? "field-input h-8 py-0 text-xs" : "field-input";

  return (
    <div className={compact ? "flex flex-wrap items-center gap-2" : "space-y-3"}>
      <div className={compact ? "flex items-center gap-2" : "grid gap-4 sm:grid-cols-2"}>
        <div>
          <label htmlFor={providerId} className={compact ? "sr-only" : "mb-1.5 block text-sm font-medium text-fg"}>
            Proveedor de IA
          </label>
          <select
            id={providerId}
            value={selection.provider}
            disabled={disabled || !catalog}
            onChange={(e) => select({ provider: e.target.value as LLMProvider, model: null })}
            className={`${selectClass} ${compact ? "w-28" : ""}`}
          >
            {OPTION_ORDER.map((p) => {
              const info = catalog?.providers.find((x) => x.provider === p);
              const unusable = p !== "auto" && info && (!info.enabled || !info.configured);
              return (
                <option key={p} value={p} disabled={!!unusable}>
                  {PROVIDER_LABELS[p]}
                  {unusable ? " (no configurado)" : ""}
                </option>
              );
            })}
          </select>
        </div>
        <div>
          <label htmlFor={modelId} className={compact ? "sr-only" : "mb-1.5 block text-sm font-medium text-fg"}>
            Modelo
          </label>
          {selection.provider === "auto" ? (
            <p id={modelId} className={compact ? "text-xs text-fg-muted" : "field-input flex items-center text-fg-muted"}>
              {autoOrder.length
                ? autoOrder
                    .map((p) => {
                      const info = catalog?.providers.find((x) => x.provider === p);
                      return `${PROVIDER_LABELS[p]}${info?.default_model ? ` (${info.default_model})` : ""}`;
                    })
                    .join(" → ")
                : "Sin proveedores en el orden de Auto"}
            </p>
          ) : (
            <select
              id={modelId}
              value={model}
              disabled={disabled || !models.length}
              onChange={(e) => select({ provider: selection.provider, model: e.target.value })}
              className={`${selectClass} ${compact ? "max-w-[14rem]" : ""} font-mono`}
            >
              {models.length === 0 && <option value="">Sin modelos</option>}
              {models.map((m) => (
                <option key={m} value={m}>
                  {m}
                  {m === providerInfo?.default_model ? " (predeterminado)" : ""}
                </option>
              ))}
            </select>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2">
        <HealthBadge health={currentHealth} />
        {healthTarget && (
          <button
            type="button"
            onClick={() => checkHealth(healthTarget, healthTargetModel, true)}
            disabled={currentHealth === "checking"}
            aria-label="Comprobar disponibilidad"
            title="Comprobar disponibilidad"
            className="rounded p-1 text-fg-subtle hover:bg-surface-2 hover:text-fg disabled:opacity-50"
          >
            <IconRefresh className="h-3.5 w-3.5" />
          </button>
        )}
        {!compact && selection.provider === "auto" && (
          <span className="text-xs text-fg-subtle">Se usa el primero disponible; si falla, el siguiente.</span>
        )}
      </div>
    </div>
  );
}
