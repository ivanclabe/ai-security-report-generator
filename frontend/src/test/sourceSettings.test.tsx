import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SourceSettings } from "../types";

vi.mock("../services/api", () => ({
  getSourceSettings: vi.fn(),
  testSourceSettings: vi.fn(),
  saveSourceSettings: vi.fn(),
  getSourceStatus: vi.fn(async () => ({ configured: true, missing: [], host: "10.2.85.8", uses_https: false, origin: "app", provider_active: true })),
}));

import * as api from "../services/api";
import { SourceSettingsPage } from "../pages/SourceSettingsPage";
import { useAuthStore } from "../store/useAuthStore";

const stored: SourceSettings = {
  scheme: "http",
  host: "10.2.85.8",
  base_path: "/ProyectoSOC/views",
  alarms_path: "/detallado_alarmas.php",
  notifications_path: "/indicadores.php",
  alarms_url: "http://10.2.85.8/ProyectoSOC/views/detallado_alarmas.php",
  notifications_url: "http://10.2.85.8/ProyectoSOC/views/indicadores.php",
  username: "analista.demo",
  password_set: true,
  verify_tls: true,
  timeout_seconds: 30,
  alarms_limit: 1000,
  reconcile_indicators: true,
  origin: "app",
  revision: 3,
  updated_at: "2026-10-02T10:00:00Z",
  updated_by: "user-admin",
  provider_active: true,
  encryption_ready: true,
};

function renderPage() {
  return render(
    <MemoryRouter>
      <SourceSettingsPage />
    </MemoryRouter>,
  );
}

describe("Fuente de Datos", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getSourceSettings).mockResolvedValue(stored);
    useAuthStore.setState({ me: { email: "a@soc.test", display_name: "A", role: "admin", is_admin: true } });
  });

  it("shows the configuration with a masked, empty password field and an http warning", async () => {
    renderPage();
    expect(await screen.findByDisplayValue("10.2.85.8")).toBeInTheDocument();
    expect(screen.getByLabelText("Contraseña")).toHaveValue("");
    expect(screen.getByPlaceholderText("•••••••• (guardada)")).toBeInTheDocument();
    expect(screen.getByText(/Conexión sin cifrar/)).toBeInTheDocument();
    expect(screen.getByText("http://10.2.85.8/ProyectoSOC/views/detallado_alarmas.php")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Guardar" })).toBeDisabled();
  });

  it("changing only the IP saves with the current revision and keeps the stored password", async () => {
    vi.mocked(api.saveSourceSettings).mockResolvedValue({
      saved: true,
      test: { ok: true, message: "Conexión correcta con 10.2.85.9.", login_method: "form", elapsed_seconds: 0.7 },
      settings: { ...stored, host: "10.2.85.9", revision: 4 },
    });
    renderPage();
    fireEvent.change(await screen.findByDisplayValue("10.2.85.8"), { target: { value: "10.2.85.9" } });
    expect(screen.getByText("http://10.2.85.9/ProyectoSOC/views/indicadores.php")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));

    await waitFor(() => expect(api.saveSourceSettings).toHaveBeenCalled());
    const [input, opts] = vi.mocked(api.saveSourceSettings).mock.calls[0];
    expect(input.host).toBe("10.2.85.9");
    expect(input.password).toBe("");
    expect(opts).toEqual({ skipTest: false, revision: 3 });
    expect(await screen.findByText(/Guardado\. Conexión correcta/)).toBeInTheDocument();
  });

  it("offers to save without testing when the connection test fails", async () => {
    vi.mocked(api.saveSourceSettings).mockResolvedValueOnce({
      saved: false,
      test: { ok: false, message: "No se pudo conectar a 10.2.85.9.", login_method: null, elapsed_seconds: null },
      settings: stored,
    });
    renderPage();
    fireEvent.change(await screen.findByDisplayValue("10.2.85.8"), { target: { value: "10.2.85.9" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    expect(await screen.findByText(/No se guardó: No se pudo conectar/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Guardar sin probar" })).toBeInTheDocument();
  });

  it("operators only see the status, never the settings form", async () => {
    useAuthStore.setState({ me: { email: "o@soc.test", display_name: "O", role: "operator", is_admin: false } });
    renderPage();
    expect(await screen.findByText(/Solo un administrador puede cambiar/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Contraseña")).not.toBeInTheDocument();
    expect(api.getSourceSettings).not.toHaveBeenCalled();
  });
});
