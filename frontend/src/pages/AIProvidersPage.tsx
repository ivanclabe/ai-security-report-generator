import { useEffect, useState } from "react";
import { HealthBadge } from "../components/llm/HealthBadge";
import { IconChevronDown, IconCpu, IconEye, IconEyeOff, IconRefresh } from "../components/icons";
import { SettingsTabs } from "../components/SettingsTabs";
import { Alert } from "../components/ui/Alert";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardBody, CardHeader } from "../components/ui/Card";
import { Field, Switch } from "../components/ui/Field";
import { Page, PageHeader } from "../components/ui/PageHeader";
import { LoadingBlock } from "../components/ui/Spinner";
import { formatDateTime } from "../lib/format";
import * as api from "../services/api";
import { PROVIDER_LABELS, useLLMStore } from "../store/useLLMStore";
import { toast } from "../store/useToastStore";
import type {
  LLMHealth,
  LLMParams,
  LLMProvider,
  LLMProviderInput,
  LLMProviderKind,
  LLMProviderSettings,
  LLMProvidersAdmin,
  LLMRouting,
  LLMVendorOption,
} from "../types";

const DESCRIPTIONS: Record<LLMProviderKind, string> = {
  cloud: "Modelos en la nube (Anthropic, OpenAI, Google). Requiere API key.",
  vllm: "Servidor vLLM propio con API compatible con OpenAI (p. ej. http://llm-server:8000).",
  local: "Runtime local (Ollama u otro servidor compatible), independiente de vLLM.",
};

function toInput(p: LLMProviderSettings): LLMProviderInput {
  return {
    vendor: p.vendor,
    enabled: p.enabled,
    base_url: p.base_url,
    api_key: "",
    clear_api_key: false,
    default_model: p.default_model,
    manual_models: p.manual_models,
    discovery_enabled: p.discovery_enabled,
    params: p.params,
  };
}

const numberOrNull = (value: string) => (value.trim() === "" ? null : Number(value));

// ---- routing -----------------------------------------------------------------------------------

function RoutingCard({ routing, onSaved }: { routing: LLMRouting; onSaved: (r: LLMRouting) => void }) {
  const [form, setForm] = useState(routing);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const changed = JSON.stringify({ ...form, revision: 0 }) !== JSON.stringify({ ...routing, revision: 0 });
  const kinds: LLMProviderKind[] = ["vllm", "cloud", "local"];
  const excluded = kinds.filter((k) => !form.auto_order.includes(k));

  function move(index: number, delta: number) {
    const order = [...form.auto_order];
    const [item] = order.splice(index, 1);
    order.splice(index + delta, 0, item);
    setForm({ ...form, auto_order: order });
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const saved = await api.saveLLMRouting(
        {
          default_provider: form.default_provider,
          auto_order: form.auto_order,
          health_ttl_seconds: form.health_ttl_seconds,
          preflight_check: form.preflight_check,
          runtime_fallback: form.runtime_fallback,
        },
        routing.origin === "app" ? routing.revision : undefined,
      );
      onSaved(saved);
      setForm(saved);
      toast("Enrutamiento de IA guardado.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title="Enrutamiento"
        description="Proveedor predeterminado y reglas del modo Auto (prioridad, verificación y fallback)."
        icon={<IconCpu className="h-4 w-4" />}
      />
      <CardBody className="space-y-5">
        <Field label="Proveedor predeterminado" hint="Lo usan quienes no eligieron uno propio.">
          {(p) => (
            <select
              {...p}
              value={form.default_provider}
              onChange={(e) => setForm({ ...form, default_provider: e.target.value as LLMProvider })}
              className="field-input sm:max-w-xs"
            >
              {(["auto", "cloud", "vllm", "local"] as LLMProvider[]).map((v) => (
                <option key={v} value={v}>
                  {PROVIDER_LABELS[v]}
                </option>
              ))}
            </select>
          )}
        </Field>
        <fieldset>
          <legend className="mb-1.5 text-sm font-medium text-fg">Orden de prioridad de Auto</legend>
          <p className="mb-2 text-xs text-fg-subtle">Se usa el primero disponible; los siguientes son el fallback, en ese orden.</p>
          <ol className="space-y-1.5">
            {form.auto_order.map((kind, i) => (
              <li key={kind} className="flex items-center gap-2 rounded-lg border border-line bg-surface-2/50 px-3 py-2 text-sm">
                <span className="w-5 text-xs font-semibold text-fg-subtle">{i + 1}.</span>
                <span className="flex-1 font-medium text-fg">
                  {PROVIDER_LABELS[kind]}
                  {i === 0 && <span className="ml-2 text-xs font-normal text-fg-subtle">principal</span>}
                  {i > 0 && <span className="ml-2 text-xs font-normal text-fg-subtle">fallback</span>}
                </span>
                <Button size="sm" variant="ghost" disabled={i === 0} onClick={() => move(i, -1)} aria-label={`Subir ${PROVIDER_LABELS[kind]}`}>
                  ↑
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={i === form.auto_order.length - 1}
                  onClick={() => move(i, 1)}
                  aria-label={`Bajar ${PROVIDER_LABELS[kind]}`}
                >
                  ↓
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={form.auto_order.length === 1}
                  onClick={() => setForm({ ...form, auto_order: form.auto_order.filter((k) => k !== kind) })}
                  aria-label={`Quitar ${PROVIDER_LABELS[kind]} de Auto`}
                >
                  Quitar
                </Button>
              </li>
            ))}
          </ol>
          {excluded.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-2">
              {excluded.map((kind) => (
                <Button key={kind} size="sm" variant="secondary" onClick={() => setForm({ ...form, auto_order: [...form.auto_order, kind] })}>
                  + Agregar {PROVIDER_LABELS[kind]}
                </Button>
              ))}
            </div>
          )}
        </fieldset>
        <Switch
          checked={form.preflight_check}
          onChange={(v) => setForm({ ...form, preflight_check: v })}
          label="Verificar el proveedor antes de cada informe"
          description="Si el elegido no está disponible se avisa antes de empezar (o Auto pasa al siguiente)."
        />
        <Switch
          checked={form.runtime_fallback}
          onChange={(v) => setForm({ ...form, runtime_fallback: v })}
          label="Fallback durante la ejecución (Auto)"
          description="Si una llamada falla por timeout, conexión o error del servidor, continuar con el siguiente proveedor."
        />
        <Field label="Vigencia del health check (segundos)" hint="Evita comprobar en cada solicitud. 0 = siempre comprobar.">
          {(p) => (
            <input
              {...p}
              type="number"
              min={0}
              max={3600}
              value={form.health_ttl_seconds}
              onChange={(e) => setForm({ ...form, health_ttl_seconds: Number(e.target.value) })}
              className="field-input sm:max-w-[10rem]"
            />
          )}
        </Field>
        {error && <Alert tone="danger">{error}</Alert>}
        <div className="flex justify-end">
          <Button onClick={save} loading={busy} disabled={!changed}>
            Guardar enrutamiento
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}

// ---- one provider ------------------------------------------------------------------------------

function ParamsEditor({ params, onChange, disabled }: { params: LLMParams; onChange: (p: LLMParams) => void; disabled: boolean }) {
  return (
    <div className="grid gap-4 sm:grid-cols-3">
      <Field label="Temperatura" optional hint="0 a 2. Vacío = la del proveedor.">
        {(p) => (
          <input {...p} type="number" step="0.1" min={0} max={2} disabled={disabled} value={params.temperature ?? ""}
            onChange={(e) => onChange({ ...params, temperature: numberOrNull(e.target.value) })} className="field-input" />
        )}
      </Field>
      <Field label="Max tokens" optional>
        {(p) => (
          <input {...p} type="number" min={1} disabled={disabled} value={params.max_tokens ?? ""}
            onChange={(e) => onChange({ ...params, max_tokens: numberOrNull(e.target.value) })} className="field-input" />
        )}
      </Field>
      <Field label="Top P" optional hint="Ignorado si el proveedor no lo admite.">
        {(p) => (
          <input {...p} type="number" step="0.05" min={0} max={1} disabled={disabled} value={params.top_p ?? ""}
            onChange={(e) => onChange({ ...params, top_p: numberOrNull(e.target.value) })} className="field-input" />
        )}
      </Field>
      <Field label="Tiempo de espera (s)">
        {(p) => (
          <input {...p} type="number" min={1} max={900} disabled={disabled} value={params.timeout_seconds}
            onChange={(e) => onChange({ ...params, timeout_seconds: Number(e.target.value) })} className="field-input" />
        )}
      </Field>
      <Field label="Ventana de contexto" optional hint="Tokens. Informativo para modelos locales.">
        {(p) => (
          <input {...p} type="number" min={512} disabled={disabled} value={params.context_window ?? ""}
            onChange={(e) => onChange({ ...params, context_window: numberOrNull(e.target.value) })} className="field-input" />
        )}
      </Field>
      <Field label="Salida estructurada" hint="Cómo se pide JSON a servidores compatibles con OpenAI.">
        {(p) => (
          <select {...p} disabled={disabled} value={params.structured_output}
            onChange={(e) => onChange({ ...params, structured_output: e.target.value as LLMParams["structured_output"] })}
            className="field-input">
            <option value="auto">Automático</option>
            <option value="json_schema">JSON Schema</option>
            <option value="function_calling">Function calling</option>
            <option value="json_mode">JSON mode</option>
          </select>
        )}
      </Field>
    </div>
  );
}

function ProviderCard({
  provider,
  vendors,
  encryptionReady,
  onSaved,
}: {
  provider: LLMProviderSettings;
  vendors: LLMVendorOption[];
  encryptionReady: boolean;
  onSaved: (p: LLMProviderSettings) => void;
}) {
  const [form, setForm] = useState<LLMProviderInput>(toInput(provider));
  const [models, setModels] = useState<string[]>(provider.models);
  const [manualText, setManualText] = useState(provider.manual_models.join("\n"));
  const [customModel, setCustomModel] = useState(!provider.models.includes(provider.default_model) && !!provider.default_model);
  const [showKey, setShowKey] = useState(false);
  const [showParams, setShowParams] = useState(false);
  const [busy, setBusy] = useState<"test" | "save" | "models" | null>(null);
  const [health, setHealth] = useState<LLMHealth | "checking" | undefined>(undefined);
  const [message, setMessage] = useState<{ tone: "success" | "danger"; text: string } | null>(null);
  const kind = provider.provider;
  const vendor = vendors.find((v) => v.vendor === form.vendor);
  const set = <K extends keyof LLMProviderInput>(key: K, value: LLMProviderInput[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
    setMessage(null);
  };
  const input = (): LLMProviderInput => ({
    ...form,
    manual_models: manualText.split("\n").map((m) => m.trim()).filter(Boolean),
  });

  async function test() {
    setBusy("test");
    setHealth("checking");
    try {
      const result = await api.testLLMProvider(kind, input());
      setHealth(result);
      if (result.models?.length) setModels(Array.from(new Set([...result.models, ...input().manual_models])));
    } catch (err) {
      setHealth(undefined);
      setMessage({ tone: "danger", text: err instanceof Error ? err.message : "No se pudo probar." });
    } finally {
      setBusy(null);
    }
  }

  async function refreshModels() {
    setBusy("models");
    try {
      const result = await api.refreshLLMModels(kind);
      setModels(Array.from(new Set([...result.models, ...input().manual_models])));
      toast(`${result.models.length} modelos disponibles en ${provider.label}.`);
      useLLMStore.getState().load();
    } catch (err) {
      setMessage({ tone: "danger", text: err instanceof Error ? err.message : "No se pudieron obtener los modelos." });
    } finally {
      setBusy(null);
    }
  }

  async function save() {
    setBusy("save");
    setMessage(null);
    try {
      const saved = await api.saveLLMProvider(kind, input(), provider.origin === "app" ? provider.revision : undefined);
      onSaved(saved);
      setForm(toInput(saved));
      setManualText(saved.manual_models.join("\n"));
      setModels(saved.models);
      setMessage({ tone: "success", text: "Guardado. Los próximos informes usarán esta configuración." });
      useLLMStore.getState().load();
    } catch (err) {
      setMessage({ tone: "danger", text: err instanceof Error ? err.message : "No se pudo guardar." });
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            {provider.label}
            {!form.enabled && <Badge>Deshabilitado</Badge>}
          </span>
        }
        description={DESCRIPTIONS[kind]}
        icon={<IconCpu className="h-4 w-4" />}
        actions={<HealthBadge health={health} />}
      />
      <CardBody className="space-y-4">
        <Switch checked={form.enabled} onChange={(v) => set("enabled", v)} label="Habilitado" description="Disponible para seleccionarse y para Auto." />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Proveedor / runtime">
            {(p) => (
              <select {...p} value={form.vendor} onChange={(e) => set("vendor", e.target.value)} className="field-input" disabled={!!busy}>
                {vendors.map((v) => (
                  <option key={v.vendor} value={v.vendor}>
                    {v.label}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label={kind === "cloud" ? "API endpoint" : "URL del servidor"} optional={kind === "cloud"}
            hint={vendor?.default_base_url ? `Vacío = ${vendor.default_base_url}` : "Incluye el puerto, p. ej. http://llm-server:8000"}>
            {(p) => (
              <input {...p} value={form.base_url} onChange={(e) => set("base_url", e.target.value)} className="field-input font-mono"
                placeholder={vendor?.default_base_url || "http://llm-server:8000"} spellCheck={false} disabled={!!busy} />
            )}
          </Field>
          <Field
            label="API key"
            optional={!vendor?.requires_api_key}
            className="sm:col-span-2"
            hint={
              provider.api_key_set
                ? `Guardada${provider.api_key_hint ? ` (termina en ${provider.api_key_hint})` : ""}. Déjala vacía para conservarla.`
                : vendor?.requires_api_key
                  ? "Obligatoria para este proveedor."
                  : "Solo si tu servidor la exige."
            }
          >
            {(p) => (
              <span className="flex items-center gap-2">
                <span className="relative block flex-1">
                  <input
                    {...p}
                    type={showKey ? "text" : "password"}
                    value={form.api_key ?? ""}
                    onChange={(e) => {
                      set("api_key", e.target.value);
                      set("clear_api_key", false);
                    }}
                    placeholder={provider.api_key_set ? `••••••••${provider.api_key_hint ?? ""}` : ""}
                    autoComplete="new-password"
                    className="field-input pr-10"
                    disabled={!!busy || !encryptionReady}
                  />
                  <button type="button" onClick={() => setShowKey((v) => !v)} aria-label={showKey ? "Ocultar API key" : "Mostrar API key"}
                    className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-fg-subtle hover:text-fg">
                    {showKey ? <IconEyeOff className="h-4 w-4" /> : <IconEye className="h-4 w-4" />}
                  </button>
                </span>
                {provider.api_key_set && (
                  <label className="flex shrink-0 items-center gap-1.5 text-xs text-fg-muted">
                    <input type="checkbox" checked={!!form.clear_api_key} onChange={(e) => set("clear_api_key", e.target.checked)} />
                    Quitar
                  </label>
                )}
              </span>
            )}
          </Field>
        </div>

        <div className="space-y-2">
          <div className="flex flex-wrap items-end gap-2">
            <Field label="Modelo predeterminado" className="min-w-[14rem] flex-1">
              {(p) =>
                customModel ? (
                  <input {...p} value={form.default_model} onChange={(e) => set("default_model", e.target.value)}
                    className="field-input font-mono" placeholder="nombre-exacto-del-modelo" spellCheck={false} />
                ) : (
                  <select {...p} value={form.default_model} onChange={(e) => set("default_model", e.target.value)} className="field-input font-mono">
                    {!models.includes(form.default_model) && <option value={form.default_model}>{form.default_model || "Elige un modelo"}</option>}
                    {models.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                )
              }
            </Field>
            <Button variant="secondary" onClick={refreshModels} loading={busy === "models"} disabled={!!busy || provider.origin !== "app"}
              icon={<IconRefresh className="h-4 w-4" />} title={provider.origin !== "app" ? "Guarda el proveedor primero" : undefined}>
              Actualizar modelos
            </Button>
          </div>
          <button type="button" onClick={() => setCustomModel((v) => !v)} className="text-xs font-medium text-primary hover:underline">
            {customModel ? "Elegir de la lista" : "Escribir otro modelo"}
          </button>
          <p className="text-xs text-fg-subtle">
            {provider.discovered_models.length
              ? `${provider.discovered_models.length} modelos descubiertos en el proveedor.`
              : "Aún no se consultaron los modelos del proveedor."}
          </p>
        </div>

        <Field label="Modelos adicionales" optional hint="Uno por línea. Para proveedores que no permiten descubrirlos.">
          {(p) => (
            <textarea {...p} rows={2} value={manualText} onChange={(e) => setManualText(e.target.value)} className="field-input font-mono text-xs" spellCheck={false} />
          )}
        </Field>
        <Switch checked={form.discovery_enabled} onChange={(v) => set("discovery_enabled", v)} label="Descubrir modelos automáticamente"
          description="Consultar al proveedor qué modelos sirve." />

        <div className="rounded-lg border border-line">
          <button type="button" onClick={() => setShowParams((v) => !v)} aria-expanded={showParams}
            className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium text-fg">
            Parámetros de inferencia
            <IconChevronDown className={`h-4 w-4 text-fg-subtle transition-transform ${showParams ? "rotate-180" : ""}`} />
          </button>
          {showParams && (
            <div className="border-t border-line p-4">
              <ParamsEditor params={form.params} onChange={(params) => set("params", params)} disabled={!!busy} />
            </div>
          )}
        </div>

        {message && <Alert tone={message.tone}>{message.text}</Alert>}
        {health && health !== "checking" && !health.ok && health.detail && <Alert tone="warning">{health.detail}</Alert>}

        <div className="flex flex-col-reverse items-stretch justify-between gap-3 border-t border-line pt-4 sm:flex-row sm:items-center">
          <p className="text-xs text-fg-subtle">
            {provider.origin === "app" ? `Última modificación: ${formatDateTime(provider.updated_at)} · revisión ${provider.revision}` : "Valores iniciales del servidor (backend/.env)."}
          </p>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={test} loading={busy === "test"} disabled={!!busy}>
              Probar conexión
            </Button>
            <Button onClick={save} loading={busy === "save"} disabled={!!busy}>
              Guardar
            </Button>
          </div>
        </div>
      </CardBody>
    </Card>
  );
}

export function AIProvidersPage() {
  const [data, setData] = useState<LLMProvidersAdmin | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getLLMProviders()
      .then((d) => !cancelled && setData(d))
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : "No se pudo cargar la configuración."));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <Page width="narrow">
      <PageHeader title="Configuración" description="Proveedores y modelos de IA que procesan la información y redactan los informes." />
      <SettingsTabs />
      {error && <Alert tone="danger">{error}</Alert>}
      {!data && !error && <LoadingBlock label="Cargando proveedores…" />}
      {data && (
        <div className="space-y-5">
          {!data.encryption_ready && (
            <Alert tone="danger" title="No se pueden guardar API keys">
              Falta SOURCE_SECRET_KEY en el servidor: las claves se guardan cifradas y sin esa clave no es posible.
            </Alert>
          )}
          <Alert tone="info">
            Las API keys se guardan cifradas en el servidor y nunca se vuelven a mostrar completas. Las pruebas y llamadas a
            los proveedores se hacen siempre desde el backend.
          </Alert>
          <RoutingCard routing={data.routing} onSaved={(routing) => { setData({ ...data, routing }); useLLMStore.getState().load(); }} />
          {(["cloud", "vllm", "local"] as LLMProviderKind[]).map((kind) => {
            const provider = data.providers.find((p) => p.provider === kind);
            return (
              provider && (
                <ProviderCard
                  key={`${kind}-${provider.revision}`}
                  provider={provider}
                  vendors={data.vendors[kind]}
                  encryptionReady={data.encryption_ready}
                  onSaved={(saved) => setData({ ...data, providers: data.providers.map((p) => (p.provider === kind ? saved : p)) })}
                />
              )
            );
          })}
        </div>
      )}
    </Page>
  );
}
