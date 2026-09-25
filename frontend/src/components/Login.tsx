import { useId, useState } from "react";
import { useAuthStore } from "../store/useAuthStore";
import { IconEye, IconEyeOff, IconShield } from "./icons";

export function Login() {
  const login = useAuthStore((s) => s.login);
  const isLoggingIn = useAuthStore((s) => s.isLoggingIn);
  const error = useAuthStore((s) => s.error);

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const usernameId = useId();
  const passwordId = useId();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    await login(username, password);
  }

  return (
    <div className="flex h-screen w-screen items-center justify-center bg-slate-50 px-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-7 shadow-sm"
      >
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-500">
            <IconShield className="h-5 w-5 text-white" aria-hidden="true" />
          </span>
          <div>
            <h1 className="text-sm font-semibold text-slate-900">Generador de Informes de Seguridad</h1>
            <p className="text-xs text-slate-400">Centro de Operaciones de Seguridad</p>
          </div>
        </div>
        <p className="mt-5 text-sm text-slate-500">Inicia sesión para continuar.</p>

        <label htmlFor={usernameId} className="mt-5 block text-sm font-medium text-slate-700">
          Usuario
          <input
            id={usernameId}
            autoFocus
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
          />
        </label>

        <label htmlFor={passwordId} className="mt-4 block text-sm font-medium text-slate-700">
          Contraseña
          <span className="relative mt-1 block">
            <input
              id={passwordId}
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 pr-9 text-sm outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
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
        </label>

        {error && (
          <p role="alert" className="mt-3 text-sm text-red-600">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={isLoggingIn || !username || !password}
          className="mt-5 w-full rounded-lg bg-brand-500 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-600 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isLoggingIn ? "Ingresando..." : "Ingresar"}
        </button>
      </form>
    </div>
  );
}
