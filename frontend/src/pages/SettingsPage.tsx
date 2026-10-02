import type { ReactNode } from "react";
import { IconCheckCircle, IconLogout, IconMonitor, IconMoon, IconSun, IconUser } from "../components/icons";
import { Alert } from "../components/ui/Alert";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardBody, CardHeader } from "../components/ui/Card";
import { Field, Switch } from "../components/ui/Field";
import { Page, PageHeader } from "../components/ui/PageHeader";
import { Spinner } from "../components/ui/Spinner";
import { AUDIENCES } from "../lib/constants";
import { useAuthStore } from "../store/useAuthStore";
import { usePreferencesStore } from "../store/usePreferencesStore";
import type { ThemePreference, UserPreferences } from "../types";

function ThemePreview({ dark }: { dark: boolean }) {
  // A miniature of the app in that theme -- fixed colors on purpose (it previews the OTHER theme too).
  const c = dark
    ? { bg: "#0a0e0c", nav: "#0e1311", card: "#121815", line: "#28322d", text: "#e6ede9", muted: "#7e8c85", primary: "#3aaa6a" }
    : { bg: "#f6f8f7", nav: "#ffffff", card: "#ffffff", line: "#dee4e1", text: "#101814", muted: "#707d76", primary: "#00532a" };
  return (
    <span aria-hidden="true" className="flex h-20 w-full overflow-hidden rounded-md border" style={{ background: c.bg, borderColor: c.line }}>
      <span className="flex w-1/4 flex-col gap-1 border-r p-1.5" style={{ background: c.nav, borderColor: c.line }}>
        <span className="h-1.5 w-3/4 rounded" style={{ background: c.primary }} />
        <span className="h-1 w-full rounded" style={{ background: c.muted, opacity: 0.4 }} />
        <span className="h-1 w-full rounded" style={{ background: c.muted, opacity: 0.4 }} />
      </span>
      <span className="flex flex-1 flex-col gap-1.5 p-2">
        <span className="h-1.5 w-1/2 rounded" style={{ background: c.text }} />
        <span className="flex-1 rounded border p-1.5" style={{ background: c.card, borderColor: c.line }}>
          <span className="block h-1 w-3/4 rounded" style={{ background: c.muted, opacity: 0.6 }} />
          <span className="mt-1 block h-2 w-1/3 rounded" style={{ background: c.primary }} />
        </span>
      </span>
    </span>
  );
}

const THEMES: { value: ThemePreference; label: string; icon: ReactNode; preview: ReactNode }[] = [
  { value: "light", label: "Claro", icon: <IconSun className="h-4 w-4" />, preview: <ThemePreview dark={false} /> },
  { value: "dark", label: "Oscuro", icon: <IconMoon className="h-4 w-4" />, preview: <ThemePreview dark /> },
  {
    value: "system",
    label: "Según el sistema",
    icon: <IconMonitor className="h-4 w-4" />,
    preview: (
      <span className="grid w-full grid-cols-2 gap-1">
        <ThemePreview dark={false} />
        <ThemePreview dark />
      </span>
    ),
  },
];

export function SettingsPage() {
  const theme = usePreferencesStore((s) => s.theme);
  const prefs = usePreferencesStore((s) => s.preferences);
  const setTheme = usePreferencesStore((s) => s.setTheme);
  const update = usePreferencesStore((s) => s.update);
  const isSaving = usePreferencesStore((s) => s.isSaving);
  const lastSavedAt = usePreferencesStore((s) => s.lastSavedAt);
  const error = usePreferencesStore((s) => s.error);
  const me = useAuthStore((s) => s.me);
  const signOut = useAuthStore((s) => s.signOut);

  const setPref = <K extends keyof UserPreferences>(key: K, value: UserPreferences[K]) => update({ [key]: value });

  return (
    <Page width="narrow">
      <PageHeader
        title="Configuración"
        description="Tus preferencias personales. Se guardan en tu cuenta y te siguen en cualquier equipo."
        actions={
          <span className="flex items-center gap-1.5 text-xs text-fg-subtle" aria-live="polite">
            {isSaving ? (
              <>
                <Spinner className="h-3 w-3" /> Guardando…
              </>
            ) : lastSavedAt ? (
              <>
                <IconCheckCircle className="h-3.5 w-3.5 text-success" /> Cambios guardados
              </>
            ) : null}
          </span>
        }
      />
      {error && <Alert tone="danger" className="mb-4">{error}</Alert>}

      <div className="space-y-5">
        <Card>
          <CardHeader title="Apariencia" description="El tema se aplica a toda la aplicación." />
          <CardBody className="space-y-5">
            <fieldset>
              <legend className="mb-2 text-sm font-medium text-fg">Tema</legend>
              <div className="grid gap-3 sm:grid-cols-3">
                {THEMES.map((t) => {
                  const selected = theme === t.value;
                  return (
                    <label
                      key={t.value}
                      className={`cursor-pointer rounded-xl border-2 p-2.5 transition-colors ${
                        selected ? "border-primary bg-primary-subtle/40" : "border-line hover:border-line-strong"
                      }`}
                    >
                      <input
                        type="radio"
                        name="theme"
                        value={t.value}
                        checked={selected}
                        onChange={() => setTheme(t.value)}
                        className="sr-only"
                      />
                      {t.preview}
                      <span className="mt-2 flex items-center gap-1.5 text-sm font-medium text-fg">
                        {t.icon}
                        {t.label}
                        {selected && <IconCheckCircle className="ml-auto h-4 w-4 text-primary" aria-label="Seleccionado" />}
                      </span>
                    </label>
                  );
                })}
              </div>
            </fieldset>
            <fieldset>
              <legend className="mb-2 text-sm font-medium text-fg">Densidad</legend>
              <div className="inline-flex rounded-lg border border-line bg-surface-2 p-1" role="radiogroup" aria-label="Densidad">
                {(
                  [
                    ["comfortable", "Cómoda"],
                    ["compact", "Compacta"],
                  ] as const
                ).map(([value, label]) => (
                  <button
                    key={value}
                    role="radio"
                    aria-checked={prefs.density === value}
                    onClick={() => setPref("density", value)}
                    className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                      prefs.density === value ? "bg-surface text-fg shadow-sm" : "text-fg-muted hover:text-fg"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <p className="mt-1.5 text-xs text-fg-subtle">Compacta muestra más información en pantalla.</p>
            </fieldset>
            <Switch
              checked={prefs.reduce_motion}
              onChange={(v) => setPref("reduce_motion", v)}
              label="Reducir animaciones"
              description="Desactiva transiciones y animaciones de la interfaz."
            />
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Informes" description="Valores por defecto del formulario «Generar informe»." />
          <CardBody className="grid gap-4 sm:grid-cols-2">
            <Field label="Formato por defecto">
              {(p) => (
                <select
                  {...p}
                  value={prefs.default_format}
                  onChange={(e) => setPref("default_format", e.target.value as UserPreferences["default_format"])}
                  className="field-input"
                >
                  <option value="docx">Word (.docx)</option>
                  <option value="pdf">PDF (.pdf)</option>
                </select>
              )}
            </Field>
            <Field label="Nivel de detalle por defecto">
              {(p) => (
                <select {...p} value={prefs.default_audience} onChange={(e) => setPref("default_audience", e.target.value)} className="field-input">
                  {AUDIENCES.map((a) => (
                    <option key={a.value} value={a.value}>
                      {a.label}
                    </option>
                  ))}
                </select>
              )}
            </Field>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="General" />
          <CardBody>
            <Field label="Página al iniciar sesión">
              {(p) => (
                <select
                  {...p}
                  value={prefs.start_page}
                  onChange={(e) => setPref("start_page", e.target.value as UserPreferences["start_page"])}
                  className="field-input sm:max-w-xs"
                >
                  <option value="/">Inicio</option>
                  <option value="/informes/nuevo">Generar informe</option>
                  <option value="/asistente">Asistente</option>
                </select>
              )}
            </Field>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Cuenta" icon={<IconUser className="h-4 w-4" />} />
          <CardBody className="flex flex-wrap items-center justify-between gap-4">
            <div className="text-sm">
              <p className="font-medium text-fg">{me?.display_name || me?.email}</p>
              <p className="text-fg-muted">{me?.email}</p>
              <div className="mt-1.5">
                <Badge tone={me?.is_admin ? "primary" : "neutral"}>{me?.is_admin ? "Administrador" : "Operador"}</Badge>
              </div>
            </div>
            <Button variant="secondary" onClick={() => signOut("user")} icon={<IconLogout className="h-4 w-4" />}>
              Cerrar sesión
            </Button>
          </CardBody>
          <p className="border-t border-line px-5 py-3 text-xs text-fg-subtle">
            La contraseña de tu cuenta la gestiona Supabase Auth; para cambiarla, contacta a un administrador.
          </p>
        </Card>
      </div>
    </Page>
  );
}
