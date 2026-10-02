import { create } from "zustand";
import * as api from "../services/api";
import type { PreferencesPayload, ThemePreference, UserPreferences } from "../types";

const STORAGE_KEY = "ai_report_gen_prefs";

export const DEFAULT_PREFERENCES: UserPreferences = {
  default_format: "docx",
  default_audience: "",
  start_page: "/",
  density: "comfortable",
  reduce_motion: false,
};

interface PreferencesState {
  theme: ThemePreference;
  preferences: UserPreferences;
  isSaving: boolean;
  lastSavedAt: string | null;
  error: string | null;

  load: () => Promise<void>;
  setTheme: (theme: ThemePreference) => Promise<void>;
  update: (patch: Partial<UserPreferences>) => Promise<void>;
}

function readCached(): PreferencesPayload {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}") as Partial<PreferencesPayload>;
    return { theme: raw.theme ?? "system", preferences: { ...DEFAULT_PREFERENCES, ...(raw.preferences ?? {}) } };
  } catch {
    return { theme: "system", preferences: DEFAULT_PREFERENCES };
  }
}

function writeCache(payload: PreferencesPayload) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ theme: payload.theme, preferences: payload.preferences }));
  } catch {
    // storage unavailable: preferences still apply for this session
  }
}

const systemDark = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches;

/** Applies theme/density/motion to <html>: every component reads the CSS tokens. */
export function applyPreferences(theme: ThemePreference, prefs: UserPreferences) {
  const root = document.documentElement;
  const dark = theme === "dark" || (theme === "system" && systemDark());
  root.classList.toggle("dark", dark);
  root.classList.toggle("reduce-motion", prefs.reduce_motion);
  if (prefs.density === "compact") root.dataset.density = "compact";
  else delete root.dataset.density;
}

const cached = readCached();

export const usePreferencesStore = create<PreferencesState>((set, get) => {
  async function persist(next: PreferencesPayload) {
    set({ theme: next.theme, preferences: next.preferences, isSaving: true, error: null });
    applyPreferences(next.theme, next.preferences);
    writeCache(next);
    try {
      const saved = await api.savePreferences(next);
      set({ isSaving: false, lastSavedAt: saved.updated_at ?? new Date().toISOString() });
    } catch (err) {
      set({ isSaving: false, error: err instanceof Error ? err.message : "No se pudieron guardar tus preferencias." });
    }
  }

  return {
    theme: cached.theme,
    preferences: cached.preferences,
    isSaving: false,
    lastSavedAt: null,
    error: null,

    load: async () => {
      try {
        const remote = await api.getPreferences();
        const preferences = { ...DEFAULT_PREFERENCES, ...remote.preferences };
        set({ theme: remote.theme, preferences, lastSavedAt: remote.updated_at ?? null });
        applyPreferences(remote.theme, preferences);
        writeCache({ theme: remote.theme, preferences });
      } catch {
        // keep the cached ones: the app still works with local preferences
      }
    },

    setTheme: (theme) => persist({ theme, preferences: get().preferences }),
    update: (patch) => persist({ theme: get().theme, preferences: { ...get().preferences, ...patch } }),
  };
});

// Follow the OS while the preference is "system".
if (typeof window !== "undefined" && window.matchMedia) {
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => {
    const { theme, preferences } = usePreferencesStore.getState();
    if (theme === "system") applyPreferences(theme, preferences);
  });
}
