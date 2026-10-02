import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  IconArrowRight,
  IconChevronDown,
  IconEye,
  IconEyeOff,
  IconLock,
  IconRefresh,
  IconServer,
} from "../components/icons";
import { Alert } from "../components/ui/Alert";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardBody, CardHeader } from "../components/ui/Card";
import { Field, Switch } from "../components/ui/Field";
import { Page, PageHeader } from "../components/ui/PageHeader";
import { LoadingBlock } from "../components/ui/Spinner";
import { formatDateTime } from "../lib/format";
import * as api from "../services/api";
import { useAuthStore } from "../store/useAuthStore";
import { useSourceStatusStore } from "../store/useSourceStatusStore";
import { toast } from "../store/useToastStore";
import type { SourceSettings, SourceSettingsInput } from "../types";

type Outcome = { tone: "success" | "danger" | "warning"; message: string; offerSkipTest?: boolean };

function toInput(s: SourceSettings): SourceSettingsInput {
  return {
    scheme: s.scheme,
    host: s.host,
    base_path: s.base_path,
    alarms_path: s.alarms_path,
    notifications_path: s.notifications_path,
    username: s.username,
    password: "",
    verify_tls: s.verify_tls,
    timeout_seconds: s.timeout_seconds,
    alarms_limit: s.alarms_limit,
    reconcile_indicators: s.reconcile_indicators,
  };
}

function previewUrl(input: SourceSettingsInput, path: string): string {
  if (/^https?:\/\//i.test(path.trim())) return path.trim();
  if (!input.host.trim()) return "—";
  const base = input.base_path.trim() ? `/${input.base_path.trim().replace(/^\/+|\/+$/g, "")}` : "";
  return `${input.scheme}://${input.host.trim()}${base}/${path.trim().replace(/^\/+/, "")}`;
}

function StatusOnly() {
  const status = useSourceStatusStore((s) => s.status);
  return (
    <Page width="narrow">
      <PageHeader eyebrow="Administración" title="Fuente de datos" description="Conexión con el servidor de Alertas y Notificaciones." />
      <Card>
        <CardHeader title="Estado" icon={<IconServer className="h-4 w-4" />} />
        <CardBody className="space-y-3 text-sm">
          {!status ? (
            <LoadingBlock />
          ) : status.configured ? (
            <>
              <Badge tone="success" dot>
                Configurada
              </Badge>
              <p className="text-fg-muted">
                Servidor: <span className="font-mono text-fg">{status.host}</span>
              </p>
            </>
          ) : (
            <>
              <Badge tone="warning" dot>
                Sin configurar
              </Badge>
              <p className="text-fg-muted">Falta {status.missing.join(", ")}.</p>
            </>
          )}
          <Alert tone="info">
            Solo un administrador puede cambiar la dirección o las credenciales de la fuente. Si algo no funciona,
            avísale indicando el mensaje de error que viste.
          </Alert>
        </CardBody>
      </Card>
    </Page>
  );
}

export function SourceSettingsPage() {
  const isAdmin = useAuthStore((s) => s.me?.is_admin);
  return isAdmin ? <SourceSettingsEditor /> : <StatusOnly />;
}

function SourceSettingsEditor() {
  const location = useLocation();
  const returnTo = (location.state as { from?: string } | null)?.from;
  const reloadStatus = useSourceStatusStore((s) => s.load);

  const [settings, setSettings] = useState<SourceSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [form, setForm] = useState<SourceSettingsInput | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [busy, setBusy] = useState<"test" | "save" | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [savedNow, setSavedNow] = useState(false);

  async function fetchSettings() {
    try {
      const s = await api.getSourceSettings();
      setSettings(s);
      setForm(toInput(s));
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "No se pudo cargar la configuración.");
    }
  }

  function load() {
    setLoadError(null);
    setOutcome(null);
    fetchSettings();
  }

  useEffect(() => {
    let cancelled = false;
    api
      .getSourceSettings()
      .then((s) => {
        if (cancelled) return;
        setSettings(s);
        setForm(toInput(s));
      })
      .catch((err) => !cancelled && setLoadError(err instanceof Error ? err.message : "No se pudo cargar la configuración."));
    return () => {
      cancelled = true;
    };
  }, []);

  const changed = useMemo(() => {
    if (!settings || !form) return false;
    const base = toInput(settings);
    return (Object.keys(base) as (keyof SourceSettingsInput)[]).some((k) => k !== "password" && base[k] !== form[k]) || !!form.password;
  }, [settings, form]);

  if (loadError) {
    return (
      <Page width="narrow">
        <PageHeader eyebrow="Administración" title="Fuente de datos" />
        <Alert tone="danger" action={<Button size="sm" variant="secondary" onClick={load}>Reintentar</Button>}>
          {loadError}
        </Alert>
      </Page>
    );
  }
  if (!settings || !form) {
    return (
      <Page width="narrow">
        <PageHeader eyebrow="Administración" title="Fuente de datos" />
        <LoadingBlock label="Cargando configuración…" />
      </Page>
    );
  }

  const set = <K extends keyof SourceSettingsInput>(key: K, value: SourceSettingsInput[K]) => {
    setForm((f) => (f ? { ...f, [key]: value } : f));
    setOutcome(null);
    setSavedNow(false);
  };
  const passwordRequired = !settings.password_set;
  const canSubmit = !!form.host.trim() && !!form.username.trim() && (!passwordRequired || !!form.password);
  const insecure = form.scheme === "http";

  async function test() {
    if (!form) return;
    setBusy("test");
    setOutcome(null);
    try {
      const result = await api.testSourceSettings(form);
      setOutcome({ tone: result.ok ? "success" : "danger", message: result.message });
    } catch (err) {
      setOutcome({ tone: "danger", message: err instanceof Error ? err.message : "No se pudo probar la conexión." });
    } finally {
      setBusy(null);
    }
  }

  async function save(skipTest = false) {
    if (!form || !settings) return;
    setBusy("save");
    setOutcome(null);
    try {
      const result = await api.saveSourceSettings(form, { skipTest, revision: settings.origin === "app" ? settings.revision : undefined });
      if (!result.saved) {
        setOutcome({ tone: "danger", message: `No se guardó: ${result.test?.message ?? "la prueba de conexión falló."}`, offerSkipTest: true });
        return;
      }
      setSettings(result.settings);
      setForm(toInput(result.settings));
      setSavedNow(true);
      setOutcome({
        tone: skipTest ? "warning" : "success",
        message: skipTest
          ? "Guardado sin probar la conexión. Prueba la conexión cuando la red esté disponible."
          : `Guardado. ${result.test?.message ?? ""} Los próximos informes usarán esta configuración.`,
      });
      toast("Fuente de datos actualizada.");
      reloadStatus();
    } catch (err) {
      setOutcome({ tone: "danger", message: err instanceof Error ? err.message : "No se pudo guardar." });
    } finally {
      setBusy(null);
    }
  }

  return (
    <Page width="narrow">
      <PageHeader
        eyebrow="Administración"
        title="Fuente de datos"
        description="Servidor del que se descargan las Alertas (export de alarmas) y las Notificaciones (panel de indicadores)."
        actions={
          <Button variant="ghost" onClick={load} icon={<IconRefresh className="h-4 w-4" />} disabled={!!busy}>
            Recargar
          </Button>
        }
      />

      <div className="space-y-5">
        {!settings.provider_active && (
          <Alert tone="info">La app usa datos de demostración (DATA_PROVIDER=mock). Esta configuración se aplicará al activar la fuente real.</Alert>
        )}
        {!settings.encryption_ready && (
          <Alert tone="danger" title="No se puede guardar la contraseña">
            Falta SOURCE_SECRET_KEY en el servidor: la contraseña se guarda cifrada y sin esa clave no es posible.
          </Alert>
        )}
        {returnTo && savedNow && (
          <Alert
            tone="success"
            action={
              <Link to={returnTo} className="inline-flex items-center gap-1 text-xs font-semibold underline">
                Volver <IconArrowRight className="h-3.5 w-3.5" />
              </Link>
            }
          >
            Listo. Ya puedes volver a donde estabas.
          </Alert>
        )}

        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (canSubmit && changed && !busy) save();
          }}
          className="space-y-5"
        >
          <Card>
            <CardHeader title="Servidor" description="Para un cambio de IP basta con editar el host." icon={<IconServer className="h-4 w-4" />} />
            <CardBody className="grid gap-4 sm:grid-cols-[8rem_1fr]">
              <Field label="Protocolo">
                {(p) => (
                  <select {...p} value={form.scheme} onChange={(e) => set("scheme", e.target.value as "http" | "https")} className="field-input" disabled={!!busy}>
                    <option value="https">https</option>
                    <option value="http">http</option>
                  </select>
                )}
              </Field>
              <Field label="IP o host" hint="Ej.: 10.2.85.8 o soc.empresa.com:8443">
                {(p) => (
                  <input
                    {...p}
                    value={form.host}
                    onChange={(e) => set("host", e.target.value)}
                    className="field-input font-mono"
                    spellCheck={false}
                    autoComplete="off"
                    placeholder="10.2.85.8"
                    disabled={!!busy}
                  />
                )}
              </Field>
              <Field label="Ruta base" optional className="sm:col-span-2" hint="Prefijo común de los endpoints, p. ej. /ProyectoSOC/views">
                {(p) => (
                  <input
                    {...p}
                    value={form.base_path}
                    onChange={(e) => set("base_path", e.target.value)}
                    className="field-input font-mono"
                    spellCheck={false}
                    autoComplete="off"
                    disabled={!!busy}
                  />
                )}
              </Field>
              {insecure && (
                <Alert tone="warning" className="sm:col-span-2">
                  Conexión sin cifrar (http): el usuario, la contraseña y los datos viajan en claro. Úsala solo a través de la VPN y
                  solicita https al proveedor.
                </Alert>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Endpoints" description="Ruta relativa a la ruta base, o una URL completa si vive en otro servidor." />
            <CardBody className="space-y-4">
              <Field label="URL de Alertas" hint={<span className="break-all font-mono">{previewUrl(form, form.alarms_path)}</span>}>
                {(p) => (
                  <input
                    {...p}
                    value={form.alarms_path}
                    onChange={(e) => set("alarms_path", e.target.value)}
                    className="field-input font-mono"
                    spellCheck={false}
                    disabled={!!busy}
                  />
                )}
              </Field>
              <Field label="URL de Notificaciones" hint={<span className="break-all font-mono">{previewUrl(form, form.notifications_path)}</span>}>
                {(p) => (
                  <input
                    {...p}
                    value={form.notifications_path}
                    onChange={(e) => set("notifications_path", e.target.value)}
                    className="field-input font-mono"
                    spellCheck={false}
                    disabled={!!busy}
                  />
                )}
              </Field>
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="Autenticación"
              description="La fuente pide usuario y contraseña. La contraseña se guarda cifrada y nunca se vuelve a mostrar."
              icon={<IconLock className="h-4 w-4" />}
            />
            <CardBody className="grid gap-4 sm:grid-cols-2">
              <Field label="Usuario">
                {(p) => (
                  <input
                    {...p}
                    value={form.username}
                    onChange={(e) => set("username", e.target.value)}
                    className="field-input"
                    autoComplete="off"
                    spellCheck={false}
                    disabled={!!busy}
                  />
                )}
              </Field>
              <Field
                label="Contraseña"
                hint={settings.password_set ? "Déjala vacía para conservar la actual." : "Obligatoria la primera vez."}
              >
                {(p) => (
                  <span className="relative block">
                    <input
                      {...p}
                      type={showPassword ? "text" : "password"}
                      value={form.password ?? ""}
                      onChange={(e) => set("password", e.target.value)}
                      autoComplete="new-password"
                      placeholder={settings.password_set ? "•••••••• (guardada)" : ""}
                      className="field-input pr-10"
                      disabled={!!busy || !settings.encryption_ready}
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword((v) => !v)}
                      aria-label={showPassword ? "Ocultar contraseña" : "Mostrar contraseña"}
                      className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-fg-subtle hover:text-fg"
                    >
                      {showPassword ? <IconEyeOff className="h-4 w-4" /> : <IconEye className="h-4 w-4" />}
                    </button>
                  </span>
                )}
              </Field>
            </CardBody>
          </Card>

          <Card>
            <button
              type="button"
              onClick={() => setShowAdvanced((v) => !v)}
              aria-expanded={showAdvanced}
              className="flex w-full items-center justify-between px-5 py-4 text-left"
            >
              <span>
                <span className="block text-sm font-semibold text-fg">Opciones avanzadas</span>
                <span className="block text-xs text-fg-muted">TLS, tiempo de espera, límite de filas y conciliación.</span>
              </span>
              <IconChevronDown className={`h-4 w-4 text-fg-subtle transition-transform ${showAdvanced ? "rotate-180" : ""}`} />
            </button>
            {showAdvanced && (
              <CardBody className="space-y-4 border-t border-line">
                <Switch
                  checked={form.verify_tls}
                  onChange={(v) => set("verify_tls", v)}
                  label="Verificar el certificado TLS"
                  description="Solo aplica con https. Mantenlo activo; desactivarlo permite suplantar el servidor."
                  disabled={!!busy}
                />
                <Switch
                  checked={form.reconcile_indicators}
                  onChange={(v) => set("reconcile_indicators", v)}
                  label="Conciliar Alertas con Notificaciones"
                  description="Compara el total de alertas con el panel y avisa si no coinciden."
                  disabled={!!busy}
                />
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="Tiempo de espera (s)" hint="Entre 1 y 300.">
                    {(p) => (
                      <input
                        {...p}
                        type="number"
                        min={1}
                        max={300}
                        value={form.timeout_seconds}
                        onChange={(e) => set("timeout_seconds", Number(e.target.value))}
                        className="field-input"
                        disabled={!!busy}
                      />
                    )}
                  </Field>
                  <Field label="Límite de filas por consulta" hint="Valor de limite= en el export.">
                    {(p) => (
                      <input
                        {...p}
                        type="number"
                        min={1}
                        max={100000}
                        value={form.alarms_limit}
                        onChange={(e) => set("alarms_limit", Number(e.target.value))}
                        className="field-input"
                        disabled={!!busy}
                      />
                    )}
                  </Field>
                </div>
              </CardBody>
            )}
          </Card>

          {outcome && (
            <Alert
              tone={outcome.tone}
              action={
                outcome.offerSkipTest && (
                  <Button size="sm" variant="secondary" onClick={() => save(true)} disabled={!!busy}>
                    Guardar sin probar
                  </Button>
                )
              }
            >
              {outcome.message}
            </Alert>
          )}

          <div className="flex flex-col-reverse items-stretch justify-between gap-3 sm:flex-row sm:items-center">
            <p className="text-xs text-fg-subtle">
              {settings.origin === "app"
                ? `Última modificación: ${formatDateTime(settings.updated_at)} · revisión ${settings.revision}`
                : "Valores iniciales del servidor (backend/.env). Al guardar pasan a gestionarse desde aquí."}
            </p>
            <div className="flex gap-2">
              <Button variant="secondary" onClick={test} loading={busy === "test"} disabled={!!busy || !canSubmit}>
                Probar conexión
              </Button>
              <Button type="submit" loading={busy === "save"} disabled={!!busy || !canSubmit || !changed}>
                {busy === "save" ? "Probando y guardando…" : "Guardar"}
              </Button>
            </div>
          </div>
        </form>
      </div>
    </Page>
  );
}
