import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../services/api";
import type { SourceSettings } from "../types";
import { SourceSettingsDialog } from "./SourceSettingsDialog";

vi.mock("../services/api", () => ({
  getSourceSettings: vi.fn(),
  testSourceSettings: vi.fn(),
  saveSourceSettings: vi.fn(),
}));

const current: SourceSettings = {
  base_url: "http://10.2.85.8/ProyectoSOC/views",
  username: "analista.demo",
  password_set: true,
  uses_https: false,
  origin: "env",
  updated_at: null,
  updated_by: null,
  provider_active: true,
};

describe("SourceSettingsDialog", () => {
  beforeEach(() => {
    vi.mocked(api.getSourceSettings).mockResolvedValue(current);
  });

  it("shows the current address and user but never a password", async () => {
    render(<SourceSettingsDialog onClose={() => {}} />);

    expect(await screen.findByDisplayValue(current.base_url)).toBeInTheDocument();
    expect(screen.getByDisplayValue("analista.demo")).toBeInTheDocument();
    expect(screen.getByLabelText("Contraseña")).toHaveValue("");
    expect(screen.getByText(/Conexión sin cifrar/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Guardar" })).toBeDisabled(); // nothing changed yet
  });

  it("saves a new IP keeping the current password and offers to save without testing if it fails", async () => {
    vi.mocked(api.saveSourceSettings).mockResolvedValueOnce({
      saved: false,
      test: { ok: false, message: "No se pudo conectar a 10.2.85.9.", login_method: null, elapsed_seconds: null },
      settings: current,
    });
    render(<SourceSettingsDialog onClose={() => {}} />);

    const url = await screen.findByLabelText("Dirección del servidor");
    fireEvent.change(url, { target: { value: "http://10.2.85.9/ProyectoSOC/views" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));

    await waitFor(() =>
      expect(api.saveSourceSettings).toHaveBeenCalledWith(
        { base_url: "http://10.2.85.9/ProyectoSOC/views", username: "analista.demo", password: undefined },
        false,
      ),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("No se guardó: No se pudo conectar a 10.2.85.9.");
    expect(screen.getByRole("button", { name: /Guardar de todos modos/ })).toBeInTheDocument();
  });
});
