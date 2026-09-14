import { create } from "zustand";
import * as api from "../services/api";

interface AuthState {
  isAuthenticated: boolean;
  username: string | null;
  isLoggingIn: boolean;
  error: string | null;

  login: (username: string, password: string) => Promise<boolean>;
  logout: () => void;
}

const USERNAME_STORAGE_KEY = "ai_report_gen_username";

function readStoredUsername(): string | null {
  try {
    return localStorage.getItem(USERNAME_STORAGE_KEY);
  } catch {
    return null;
  }
}

export const useAuthStore = create<AuthState>((set) => ({
  isAuthenticated: !!api.getAuthToken(),
  username: readStoredUsername(),
  isLoggingIn: false,
  error: null,

  login: async (username: string, password: string) => {
    set({ isLoggingIn: true, error: null });
    try {
      const result = await api.login(username, password);
      api.setAuthToken(result.access_token);
      try {
        localStorage.setItem(USERNAME_STORAGE_KEY, result.username);
      } catch {
        // ignore -- session still works without persisted username
      }
      set({ isAuthenticated: true, username: result.username, isLoggingIn: false });
      return true;
    } catch (err) {
      set({
        isLoggingIn: false,
        error: err instanceof Error ? err.message : "No se pudo iniciar sesión.",
      });
      return false;
    }
  },

  logout: () => {
    api.setAuthToken(null);
    try {
      localStorage.removeItem(USERNAME_STORAGE_KEY);
    } catch {
      // ignore
    }
    set({ isAuthenticated: false, username: null });
  },
}));

api.setUnauthorizedHandler(() => useAuthStore.getState().logout());
