import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { LLMCatalog, LLMProvidersAdmin, LLMRunInfo } from "../types";

vi.mock("../services/api", () => ({
  getLLMCatalog: vi.fn(),
  checkLLMHealth: vi.fn(),
  savePreferences: vi.fn(async (p: unknown) => p),
  getLLMProviders: vi.fn(),
  saveLLMProvider: vi.fn(),
  testLLMProvider: vi.fn(),
  refreshLLMModels: vi.fn(),
  saveLLMRouting: vi.fn(),
}));

import { LLMRunStatus } from "../components/llm/LLMRunStatus";
import { LLMSelector } from "../components/llm/LLMSelector";
import { AIProvidersPage } from "../pages/AIProvidersPage";
import * as api from "../services/api";
import { useAuthStore } from "../store/useAuthStore";
import { describeSelection, useLLMStore } from "../store/useLLMStore";

const catalog: LLMCatalog = {
  selectable: ["auto", "cloud", "local", "vllm"],
  providers: [
    { provider: "cloud", label: "Cloud", vendor_label: "Anthropic (Claude)", enabled: true, configured: true, problem: null, default_model: "claude-sonnet-5", models: ["claude-sonnet-5", "claude-haiku-4-5"] },
    { provider: "local", label: "Local", vendor_label: "Ollama", enabled: false, configured: false, problem: "Falta la URL del proveedor.", default_model: "", models: [] },
    { provider: "vllm", label: "vLLM", vendor_label: "vLLM", enabled: true, configured: true, problem: null, default_model: "Qwen/Qwen3-32B", models: ["Qwen/Qwen3-32B", "meta-llama/Llama-3.3-70B-Instruct"] },
  ],
  routing: { default_provider: "auto", auto_order: ["vllm", "cloud"], auto_candidates: ["vllm", "cloud"], preflight_check: true, runtime_fallback: true },
  default_selection: { provider: "auto", model: null },
};

describe("AI provider selection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getLLMCatalog).mockResolvedValue(catalog);
    vi.mocked(api.checkLLMHealth).mockResolvedValue({
      provider: "vllm", status: "available", label: "Disponible", ok: true, latency_ms: 420, detail: "",
      model: "Qwen/Qwen3-32B", models_count: 2, checked_at: "",
    });
    useLLMStore.setState({ catalog: null, selection: { provider: "auto", model: null }, health: {} });
  });

  it("shows Auto's order, checks the primary and disables unconfigured providers", async () => {
    render(<LLMSelector />);
    expect(await screen.findByText("vLLM (Qwen/Qwen3-32B) → Cloud (claude-sonnet-5)")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Local \(no configurado\)/ })).toBeDisabled();
    await waitFor(() => expect(api.checkLLMHealth).toHaveBeenCalledWith("vllm", "Qwen/Qwen3-32B", false));
    expect(await screen.findByText(/Disponible · 420 ms/)).toBeInTheDocument();
  });

  it("choosing a provider lists that provider's models and saves it as the user's default", async () => {
    render(<LLMSelector />);
    fireEvent.change(await screen.findByLabelText("Proveedor de IA"), { target: { value: "vllm" } });
    const model = screen.getByLabelText("Modelo");
    expect(screen.getByRole("option", { name: "meta-llama/Llama-3.3-70B-Instruct" })).toBeInTheDocument();
    fireEvent.change(model, { target: { value: "meta-llama/Llama-3.3-70B-Instruct" } });
    expect(useLLMStore.getState().selection).toEqual({ provider: "vllm", model: "meta-llama/Llama-3.3-70B-Instruct" });
    await waitFor(() =>
      expect(api.savePreferences).toHaveBeenLastCalledWith(
        expect.objectContaining({ preferences: expect.objectContaining({ llm_provider: "vllm", llm_model: "meta-llama/Llama-3.3-70B-Instruct" }) }),
      ),
    );
    expect(describeSelection(useLLMStore.getState().selection, catalog)).toBe("vLLM · meta-llama/Llama-3.3-70B-Instruct");
  });

  it("the run status shows provider, active provider, model and a fallback", () => {
    const info: LLMRunInfo = {
      requested: "auto", requested_label: "Auto", provider: "cloud", provider_label: "Cloud", vendor: "anthropic",
      model: "claude-sonnet-5", fallbacks: [], switched: true,
      last_fallback: { from: "vllm", to: "cloud", reason: "timeout", reason_label: "Tiempo de espera agotado", stage: "runtime" },
    };
    render(<LLMRunStatus info={info} status="Analizando los datos de seguridad..." />);
    expect(screen.getByText("Auto")).toBeInTheDocument();
    expect(screen.getByText("Cloud")).toBeInTheDocument();
    expect(screen.getByText("claude-sonnet-5")).toBeInTheDocument();
    expect(screen.getByText(/Cambio de proveedor: vLLM → Cloud · motivo: Tiempo de espera agotado/)).toBeInTheDocument();
  });
});

describe("Proveedores de IA (admin)", () => {
  const admin: LLMProvidersAdmin = {
    providers: [
      { provider: "cloud", label: "Cloud", vendor: "anthropic", vendor_label: "Anthropic (Claude)", enabled: true, base_url: "", effective_base_url: "https://api.anthropic.com",
        api_key_set: true, api_key_hint: "a1b2", requires_api_key: true, default_model: "claude-sonnet-5", manual_models: [], discovered_models: ["claude-sonnet-5"],
        models: ["claude-sonnet-5"], discovery_enabled: true,
        params: { temperature: null, max_tokens: 8192, top_p: null, timeout_seconds: 120, context_window: null, structured_output: "auto" },
        revision: 2, updated_at: null, origin: "app" },
    ],
    routing: { default_provider: "cloud", auto_order: ["vllm", "cloud"], health_ttl_seconds: 30, preflight_check: true, runtime_fallback: true, revision: 1, updated_at: null, origin: "app" },
    vendors: { cloud: [{ vendor: "anthropic", label: "Anthropic (Claude)", default_base_url: "https://api.anthropic.com", requires_api_key: true }], vllm: [], local: [] },
    encryption_ready: true,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getLLMProviders).mockResolvedValue(admin);
    useAuthStore.setState({ me: { email: "a@soc.test", display_name: "A", role: "admin", is_admin: true } });
  });

  it("never shows the stored API key and saving without typing one keeps it", async () => {
    vi.mocked(api.saveLLMProvider).mockResolvedValue({ ...admin.providers[0], revision: 3 });
    render(
      <MemoryRouter>
        <AIProvidersPage />
      </MemoryRouter>,
    );
    const key = await screen.findByLabelText("API key");
    expect(key).toHaveValue("");
    expect(screen.getByPlaceholderText("••••••••a1b2")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(api.saveLLMProvider).toHaveBeenCalled());
    const [kind, input, revision] = vi.mocked(api.saveLLMProvider).mock.calls[0];
    expect(kind).toBe("cloud");
    expect(input.api_key).toBe("");
    expect(revision).toBe(2);
  });
});
