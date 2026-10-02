import { useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { IconEye, IconEyeOff, IconLock, IconShield } from "../components/icons";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Field } from "../components/ui/Field";
import { useAuthStore } from "../store/useAuthStore";
import { usePreferencesStore } from "../store/usePreferencesStore";

export function LoginPage() {
  const status = useAuthStore((s) => s.status);
  const signIn = useAuthStore((s) => s.signIn);
  const isSigningIn = useAuthStore((s) => s.isSigningIn);
  const error = useAuthStore((s) => s.error);
  const notice = useAuthStore((s) => s.notice);
  const clearMessages = useAuthStore((s) => s.clearMessages);
  const startPage = usePreferencesStore((s) => s.preferences.start_page);
  const location = useLocation();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  if (status === "signed_in") {
    const from = (location.state as { from?: string } | null)?.from;
    return <Navigate to={from && from !== "/login" ? from : startPage} replace />;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email || !password) return;
    await signIn(email, password);
  }

  return (
    <div className="flex min-h-screen bg-canvas">
      <div className="relative hidden w-[44%] flex-col justify-between overflow-hidden bg-brand-500 p-10 text-white lg:flex">
        <div
          aria-hidden="true"
          className="absolute inset-0 opacity-[0.08]"
          style={{
            backgroundImage:
              "linear-gradient(rgba(255,255,255,.6) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.6) 1px, transparent 1px)",
            backgroundSize: "28px 28px",
          }}
        />
        <div className="relative flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/15 ring-1 ring-white/25">
            <IconShield className="h-5 w-5" aria-hidden="true" />
          </span>
          <span className="text-sm font-semibold">Invotecsa</span>
        </div>
        <div className="relative">
          <h2 className="text-3xl font-semibold leading-tight">
            Informes de gestión de seguridad, listos en minutos.
          </h2>
          <p className="mt-3 max-w-md text-sm text-white/80">
            Consolida las alertas de la fuente oficial, analízalas con el asistente y entrega documentos Word o PDF
            con trazabilidad completa.
          </p>
        </div>
        <p className="relative text-xs text-white/60">Acceso restringido a personal autorizado. Toda actividad queda auditada.</p>
      </div>

      <div className="flex flex-1 items-center justify-center px-4 py-10">
        <form onSubmit={handleSubmit} className="w-full max-w-sm" noValidate>
          <div className="mb-8 flex items-center gap-2.5 lg:hidden">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-500">
              <IconShield className="h-5 w-5 text-white" aria-hidden="true" />
            </span>
            <span className="text-sm font-semibold text-fg">Invotecsa</span>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-fg">Inicia sesión</h1>
          <p className="mt-1 text-sm text-fg-muted">Usa tu cuenta corporativa de la plataforma.</p>

          <div className="mt-6 space-y-3">
            {notice && <Alert tone="warning">{notice}</Alert>}
            {error && <Alert tone="danger">{error}</Alert>}
          </div>

          <div className="mt-5 space-y-4">
            <Field label="Correo electrónico">
              {(props) => (
                <input
                  {...props}
                  type="email"
                  autoComplete="email"
                  autoFocus
                  required
                  value={email}
                  onChange={(e) => {
                    setEmail(e.target.value);
                    if (error || notice) clearMessages();
                  }}
                  className="field-input"
                  placeholder="nombre@empresa.com"
                />
              )}
            </Field>
            <Field label="Contraseña">
              {(props) => (
                <span className="relative block">
                  <input
                    {...props}
                    type={showPassword ? "text" : "password"}
                    autoComplete="current-password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="field-input pr-10"
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
          </div>

          <Button
            type="submit"
            className="mt-6 w-full"
            loading={isSigningIn || status === "loading"}
            disabled={!email || !password}
            icon={<IconLock className="h-4 w-4" aria-hidden="true" />}
          >
            {isSigningIn ? "Verificando…" : "Iniciar sesión"}
          </Button>
          <p className="mt-6 text-center text-xs text-fg-subtle">
            ¿Sin acceso o olvidaste tu contraseña? Contacta a un administrador de la plataforma.
          </p>
        </form>
      </div>
    </div>
  );
}
