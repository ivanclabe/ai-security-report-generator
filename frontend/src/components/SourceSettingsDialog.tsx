import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { getSourceSettings, saveSourceSettings, testSourceSettings } from "../services/api";
import type { SourceSettings } from "../types";
import { IconAlertCircle, IconCheckCircle, IconEye, IconEyeOff, IconServer, IconX } from "./icons";

const inputClass =
  "mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 disabled:bg-slate-50";
const labelClass = "block text-sm font-medium text-slate-700";

type Outcome = { kind: "ok" | "error"; message: string; offerSaveWithoutTest?: boolean };

function describeOrigin(settings: SourceSettings): string {
  if (settings.origin === "env") return "Valores iniciales del servidor (backend/.env).";
  const when = settings.updated_at ? new Date(settings.updated_at).toLocaleString("es-CO") : null;
  return `Guardado desde la app${settings.updated_by ? ` por ${settings.updated_by}` : ""}${when ? ` el ${when}` : ""}.`;
}

/** Configuración > Fuente de datos: dirección, usuario y contraseña del servidor de alarmas. */
export function SourceSettingsDialog({ onClose }: { onClose: () => void }) {
  const [settings, setSettings] = useState<SourceSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [baseUrl, setBaseUrl] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState<"test" | "save" | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  const titleId = useId();
  const urlId = useId();
  const userId = useId();
  const passwordId = useId();
  const firstFieldRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    getSourceSettings()
      .then((s) => {
        setSettings(s);
        setBaseUrl(s.base_url);
        setUsername(s.username);
      })
      .catch((e: Error) => setLoadError(e.message));
  }, []);

  useEffect(() => {
    if (settings) firstFieldRef.current?.focus();
  }, [settings]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !busy) onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const input = { base_url: baseUrl.trim(), username: username.trim(), password: password || undefined };
  const changed =
    settings !== null &&
    (input.base_url !== settings.base_url || input.username !== settings.username || password !== "");
  const insecure = baseUrl.trim().toLowerCase().startsWith("http://");
  const canSubmit = !!input.base_url && !!input.username && (password !== "" || !!settings?.password_set);

  async function handleTest() {
    setBusy("test");
    setOutcome(null);
    try {
      const result = await testSourceSettings(input);
      setOutcome({ kind: result.ok ? "ok" : "error", message: result.message });
    } catch (e) {
      setOutcome({ kind: "error", message: (e as Error).message });
    } finally {
      setBusy(null);
    }
  }

  async function handleSave(skipConnectionTest = false) {
    setBusy("save");
    setOutcome(null);
    try {
      const result = await saveSourceSettings(input, skipConnectionTest);
      if (!result.saved) {
        setOutcome({
          kind: "error",
          message: `No se guardó: ${result.test?.message ?? "la prueba de conexión falló."}`,
          offerSaveWithoutTest: true,
        });
        return;
      }
      setSettings(result.settings);
      setBaseUrl(result.settings.base_url);
      setUsername(result.settings.username);
      setPassword("");
      setOutcome({
        kind: "ok",
        message: skipConnectionTest
          ? "Guardado sin probar la conexión. Los próximos informes usarán estos datos."
          : `Guardado. ${result.test?.message ?? ""} Los próximos informes usarán estos datos.`,
      });
    } catch (e) {
      setOutcome({ kind: "error", message: (e as Error).message });
    } finally {
      setBusy(null);
    }
  }

  // Portal: the sidebar is a CSS-transformed drawer on small screens, which would
  // otherwise turn this fixed overlay into one clipped to the drawer's width.
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/40 px-4 py-10">
      {/* A stray click outside must not throw away what the operator typed. */}
      <div className="fixed inset-0" onClick={() => !busy && !changed && onClose()} aria-hidden="true" />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative w-full max-w-lg rounded-xl bg-white shadow-xl"
      >
        <div className="flex items-start justify-between border-b border-slate-200 px-5 py-4">
          <div className="flex items-start gap-2.5">
            <IconServer className="mt-0.5 h-5 w-5 shrink-0 text-brand-500" aria-hidden="true" />
            <div>
              <h2 id={titleId} className="text-base font-semibold text-slate-900">
                Fuente de datos
              </h2>
              <p className="mt-0.5 text-xs text-slate-500">Servidor del que se descargan las alarmas y los indicadores.</p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={!!busy}
            aria-label="Cerrar"
            className="-mr-1 rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50"
          >
            <IconX className="h-4 w-4" />
          </button>
        </div>

        {!settings && !loadError && <p className="px-5 py-8 text-sm text-slate-500">Cargando configuración…</p>}
        {loadError && (
          <p role="alert" className="flex items-center gap-1.5 px-5 py-8 text-sm text-red-600">
            <IconAlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
            No se pudo cargar la configuración: {loadError}
          </p>
        )}

        {settings && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (canSubmit && changed && !busy) handleSave();
            }}
            className="space-y-4 px-5 py-4"
          >
            {!settings.provider_active && (
              <p className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-600">
                La app está usando datos de demostración (DATA_PROVIDER=mock). Estos valores se aplicarán cuando se
                active la fuente real.
              </p>
            )}

            <div>
              <label htmlFor={urlId} className={labelClass}>
                Dirección del servidor
              </label>
              <input
                id={urlId}
                ref={firstFieldRef}
                type="text"
                inputMode="url"
                autoComplete="off"
                spellCheck={false}
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                disabled={!!busy}
                placeholder="http://10.2.85.8/ProyectoSOC/views"
                className={`${inputClass} font-mono`}
              />
              <span className="mt-1 block text-xs text-slate-400">
                Con http:// o https:// y la ruta. Para un cambio de IP, cambia solo los números.
              </span>
              {insecure && (
                <p className="mt-2 flex items-start gap-1.5 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800">
                  <IconAlertCircle className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                  Conexión sin cifrar (http): el usuario, la contraseña y los datos viajan en claro. Úsala solo a través
                  de la VPN.
                </p>
              )}
            </div>

            <div>
              <label htmlFor={userId} className={labelClass}>
                Usuario
              </label>
              <input
                id={userId}
                type="text"
                autoComplete="off"
                spellCheck={false}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                disabled={!!busy}
                className={inputClass}
              />
            </div>

            <div>
              <label htmlFor={passwordId} className={labelClass}>
                Contraseña
              </label>
              <span className="relative mt-1 block">
                <input
                  id={passwordId}
                  type={showPassword ? "text" : "password"}
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={!!busy}
                  placeholder={settings.password_set ? "•••••••• (guardada)" : ""}
                  className={`${inputClass} mt-0 pr-9`}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? "Ocultar contraseña" : "Mostrar contraseña"}
                  className="absolute inset-y-0 right-0 flex w-9 items-center justify-center text-slate-400 hover:text-slate-600"
                >
                  {showPassword ? <IconEyeOff className="h-4 w-4" /> : <IconEye className="h-4 w-4" />}
                </button>
              </span>
              <span className="mt-1 block text-xs text-slate-400">
                {settings.password_set
                  ? "Déjala vacía para conservar la actual. Por seguridad, la contraseña guardada nunca se muestra."
                  : "No hay contraseña configurada."}
              </span>
            </div>

            <p className="text-xs text-slate-400">{describeOrigin(settings)}</p>

            {outcome && (
              <div
                role={outcome.kind === "error" ? "alert" : "status"}
                className={`rounded-md px-3 py-2 text-sm ${
                  outcome.kind === "ok" ? "bg-brand-50 text-brand-700" : "bg-red-50 text-red-700"
                }`}
              >
                <p className="flex items-start gap-1.5">
                  {outcome.kind === "ok" ? (
                    <IconCheckCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                  ) : (
                    <IconAlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                  )}
                  <span>{outcome.message}</span>
                </p>
                {outcome.offerSaveWithoutTest && (
                  <button
                    type="button"
                    onClick={() => handleSave(true)}
                    disabled={!!busy}
                    className="mt-2 text-xs font-medium text-red-700 underline underline-offset-2 hover:text-red-900"
                  >
                    Guardar de todos modos (p. ej. si la VPN está desconectada)
                  </button>
                )}
              </div>
            )}

            <div className="flex flex-col-reverse gap-2 border-t border-slate-100 pt-4 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={onClose}
                disabled={!!busy}
                className="rounded-lg px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-50"
              >
                {changed ? "Cancelar" : "Cerrar"}
              </button>
              <button
                type="button"
                onClick={handleTest}
                disabled={!!busy || !canSubmit}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {busy === "test" ? "Probando…" : "Probar conexión"}
              </button>
              <button
                type="submit"
                disabled={!!busy || !canSubmit || !changed}
                className="rounded-lg bg-brand-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-600 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {busy === "save" ? "Probando y guardando…" : "Guardar"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>,
    document.body,
  );
}
