import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const supabaseMock = vi.hoisted(() => ({
  session: null as null | { access_token: string },
  signInResult: { data: { session: null as null | { access_token: string } }, error: null as null | { message: string } },
  listeners: [] as ((event: string, session: unknown) => void)[],
}));

vi.mock("../lib/supabase", () => ({
  isSupabaseConfigured: true,
  supabase: {
    auth: {
      getSession: vi.fn(async () => ({ data: { session: supabaseMock.session } })),
      onAuthStateChange: vi.fn((cb: (event: string, session: unknown) => void) => {
        supabaseMock.listeners.push(cb);
        return { data: { subscription: { unsubscribe: vi.fn() } } };
      }),
      signInWithPassword: vi.fn(async () => supabaseMock.signInResult),
      signOut: vi.fn(async () => ({ error: null })),
    },
  },
}));

const apiMock = vi.hoisted(() => ({
  me: { email: "operador@soc.test", display_name: "Operador", role: "operator", is_admin: false },
  meError: null as null | { status: number; code: string; message: string },
}));

vi.mock("../services/api", async () => {
  class ApiError extends Error {
    constructor(
      public status: number,
      message: string,
      public code: string | null = null,
    ) {
      super(message);
    }
  }
  return {
    ApiError,
    setAuthFailureHandler: vi.fn(),
    getMe: vi.fn(async () => {
      if (apiMock.meError) throw new ApiError(apiMock.meError.status, apiMock.meError.message, apiMock.meError.code);
      return apiMock.me;
    }),
    getPreferences: vi.fn(async () => ({ theme: "system", preferences: {} })),
    savePreferences: vi.fn(async (p: unknown) => p),
    reportSessionEvent: vi.fn(async () => undefined),
    reportAuthFailure: vi.fn(async () => undefined),
    getSourceStatus: vi.fn(async () => ({
      configured: false,
      missing: ["la contraseña"],
      host: "10.2.85.8",
      uses_https: false,
      origin: "env",
      provider_active: true,
    })),
    listRecentReports: vi.fn(async () => []),
    getObservabilitySummary: vi.fn(async () => {
      throw new Error("no");
    }),
    listCompanies: vi.fn(async () => []),
    listReportTemplates: vi.fn(async () => []),
    listConversations: vi.fn(async () => []),
  };
});

import App from "../App";
import * as api from "../services/api";
import { useAuthStore } from "../store/useAuthStore";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe("authentication and route protection", () => {
  beforeEach(() => {
    supabaseMock.session = null;
    supabaseMock.signInResult = { data: { session: null }, error: null };
    apiMock.meError = null;
    apiMock.me = { email: "operador@soc.test", display_name: "Operador", role: "operator", is_admin: false };
    useAuthStore.setState({ status: "loading", session: null, me: null, error: null, notice: null, isSigningIn: false });
  });

  it("sends a visitor without a session to the login screen", async () => {
    renderAt("/auditoria");
    expect(await screen.findByRole("heading", { name: "Inicia sesión" })).toBeInTheDocument();
  });

  it("restores a persisted session and shows the app", async () => {
    supabaseMock.session = { access_token: "t" };
    renderAt("/");
    expect(await screen.findByText(/Buen(os|as) (días|tardes|noches), Operador/)).toBeInTheDocument();
  });

  it("hides admin modules from operators and blocks their routes", async () => {
    supabaseMock.session = { access_token: "t" };
    renderAt("/auditoria");
    expect(await screen.findByText("Sección solo para administradores")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Observabilidad/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Fuente de datos/ })).toBeInTheDocument();
  });

  it("shows a clear message for wrong credentials and audits the failure", async () => {
    supabaseMock.signInResult = { data: { session: null }, error: { message: "Invalid login credentials" } };
    renderAt("/login");
    fireEvent.change(await screen.findByLabelText("Correo electrónico"), { target: { value: "x@soc.test" } });
    fireEvent.change(screen.getByLabelText("Contraseña"), { target: { value: "mala" } });
    fireEvent.click(screen.getByRole("button", { name: /Iniciar sesión/ }));
    expect(await screen.findByText("Correo o contraseña incorrectos.")).toBeInTheDocument();
    expect(api.reportAuthFailure).toHaveBeenCalledWith("login_failed", "x@soc.test", "Invalid login credentials");
  });

  it("refuses a Supabase user who is not a member of this app", async () => {
    supabaseMock.signInResult = { data: { session: { access_token: "t" } }, error: null };
    apiMock.meError = { status: 403, code: "not_member", message: "sin acceso" };
    renderAt("/login");
    fireEvent.change(await screen.findByLabelText("Correo electrónico"), { target: { value: "otra@app.test" } });
    fireEvent.change(screen.getByLabelText("Contraseña"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: /Iniciar sesión/ }));
    expect(await screen.findByText(/no tiene acceso a esta aplicación/)).toBeInTheDocument();
  });

  it("returns to login with a notice when the session expires", async () => {
    supabaseMock.session = { access_token: "t" };
    renderAt("/");
    await screen.findByText(/Buen(os|as) (días|tardes|noches), Operador/);
    await useAuthStore.getState().signOut("expired");
    await waitFor(() => expect(screen.getByText(/Tu sesión expiró/)).toBeInTheDocument());
    expect(api.reportAuthFailure).toHaveBeenCalledWith("session_expired", "operador@soc.test", expect.any(String));
  });

  it("logout is audited before the session is closed", async () => {
    supabaseMock.session = { access_token: "t" };
    renderAt("/");
    fireEvent.click(await screen.findByRole("button", { name: "Cerrar sesión" }));
    await screen.findByRole("heading", { name: "Inicia sesión" });
    expect(api.reportSessionEvent).toHaveBeenCalledWith("logout");
  });

  it("guides the user to Fuente de Datos when the source is not configured", async () => {
    supabaseMock.session = { access_token: "t" };
    renderAt("/informes/nuevo");
    expect(await screen.findByText("Primero hay que configurar la fuente de datos")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Ver fuente de datos/ })).toHaveAttribute("href", "/fuente-de-datos");
    expect(screen.getByRole("button", { name: /Generar informe/ })).toBeDisabled();
  });
});
