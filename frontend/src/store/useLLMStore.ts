import { create } from "zustand";
import * as api from "../services/api";
import type { LLMCatalog, LLMHealth, LLMProviderKind, LLMSelection } from "../types";
import { usePreferencesStore } from "./usePreferencesStore";

type HealthKey = string; // `${provider}|${model}`

interface LLMState {
  catalog: LLMCatalog | null;
  selection: LLMSelection;
  health: Record<HealthKey, LLMHealth | "checking">;
  error: string | null;

  load: () => Promise<void>;
  /** Changes the selection for the next reports/chat turns and saves it as the user's default. */
  select: (selection: LLMSelection, persist?: boolean) => void;
  checkHealth: (provider: LLMProviderKind, model?: string | null, refresh?: boolean) => Promise<LLMHealth | null>;
}

export const healthKey = (provider: string, model?: string | null) => `${provider}|${model ?? ""}`;

export const PROVIDER_LABELS: Record<string, string> = { auto: "Auto", cloud: "Cloud", local: "Local", vllm: "vLLM" };

export const useLLMStore = create<LLMState>((set, get) => ({
  catalog: null,
  selection: { provider: "auto", model: null },
  health: {},
  error: null,

  load: async () => {
    try {
      const catalog = await api.getLLMCatalog();
      set({ catalog, selection: catalog.default_selection, error: null });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "No se pudo cargar la configuración de IA." });
    }
  },

  select: (selection, persist = true) => {
    set({ selection });
    if (persist) {
      usePreferencesStore.getState().update({ llm_provider: selection.provider, llm_model: selection.model ?? null });
    }
  },

  checkHealth: async (provider, model, refresh = false) => {
    const key = healthKey(provider, model);
    set({ health: { ...get().health, [key]: "checking" } });
    try {
      const result = await api.checkLLMHealth(provider, model, refresh);
      set({ health: { ...get().health, [key]: result } });
      return result;
    } catch {
      const { [key]: _removed, ...rest } = get().health;
      void _removed;
      set({ health: rest });
      return null;
    }
  },
}));

/** Human description of a selection: "Auto (vLLM → Cloud)" or "vLLM · Qwen/Qwen3-32B". */
export function describeSelection(selection: LLMSelection, catalog: LLMCatalog | null): string {
  if (selection.provider === "auto") {
    const order = catalog?.routing.auto_candidates ?? [];
    return order.length ? `Auto (${order.map((p) => PROVIDER_LABELS[p]).join(" → ")})` : "Auto";
  }
  const provider = catalog?.providers.find((p) => p.provider === selection.provider);
  const model = selection.model || provider?.default_model;
  return `${PROVIDER_LABELS[selection.provider]}${model ? ` · ${model}` : ""}`;
}
