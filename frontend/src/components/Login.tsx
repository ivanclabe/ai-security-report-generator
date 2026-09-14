import { useState } from "react";
import { useAuthStore } from "../store/useAuthStore";

export function Login() {
  const login = useAuthStore((s) => s.login);
  const isLoggingIn = useAuthStore((s) => s.isLoggingIn);
  const error = useAuthStore((s) => s.error);

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    await login(username, password);
  }

  return (
    <div className="flex h-screen w-screen items-center justify-center bg-slate-50">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-6 shadow-sm"
      >
        <h1 className="text-lg font-semibold text-slate-900">Generador de Informes de Seguridad IA</h1>
        <p className="mt-1 text-sm text-slate-500">Inicia sesión para continuar.</p>

        <label className="mt-5 block text-sm font-medium text-slate-700">
          Usuario
          <input
            autoFocus
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-slate-400"
          />
        </label>

        <label className="mt-4 block text-sm font-medium text-slate-700">
          Contraseña
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-slate-400"
          />
        </label>

        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}

        <button
          type="submit"
          disabled={isLoggingIn || !username || !password}
          className="mt-5 w-full rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isLoggingIn ? "Ingresando..." : "Ingresar"}
        </button>
      </form>
    </div>
  );
}
