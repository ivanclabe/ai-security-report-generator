import { create } from "zustand";
import * as api from "../services/api";
import type { SourceStatus } from "../types";

interface SourceStatusState {
  status: SourceStatus | null;
  isLoading: boolean;
  error: string | null;
  load: () => Promise<SourceStatus | null>;
}

/** Shared "is the data source ready?" state: shell indicator, Inicio, report form. */
export const useSourceStatusStore = create<SourceStatusState>((set) => ({
  status: null,
  isLoading: false,
  error: null,
  load: async () => {
    set({ isLoading: true, error: null });
    try {
      const status = await api.getSourceStatus();
      set({ status, isLoading: false });
      return status;
    } catch (err) {
      set({ isLoading: false, error: err instanceof Error ? err.message : "No se pudo consultar la fuente." });
      return null;
    }
  },
}));
