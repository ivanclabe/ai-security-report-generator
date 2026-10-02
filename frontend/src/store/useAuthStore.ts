import type { Session } from "@supabase/supabase-js";
import { create } from "zustand";
import { isSupabaseConfigured, supabase } from "../lib/supabase";
import * as api from "../services/api";
import type { Me } from "../types";

export type AuthStatus = "loading" | "signed_out" | "signed_in";

interface AuthState {
  status: AuthStatus;
  session: Session | null;
  me: Me | null;
  isSigningIn: boolean;
  error: string | null;
  /** Why the user is on the login screen again (expired session, removed access...). */
  notice: string | null;

  init: () => () => void;
  signIn: (email: string, password: string) => Promise<boolean>;
  signOut: (reason?: "user" | "expired" | "denied") => Promise<void>;
  clearMessages: () => void;
}

const SIGN_IN_ERRORS: Record<string, string> = {
  "Invalid login credentials": "Correo o contraseña incorrectos.",
  "Email not confirmed": "Tu correo aún no está confirmado. Revisa el mensaje de bienvenida.",
  "Too many requests": "Demasiados intentos seguidos. Espera unos minutos.",
};

function signInMessage(message: string): string {
  for (const [needle, text] of Object.entries(SIGN_IN_ERRORS)) {
    if (message.includes(needle)) return text;
  }
  return "No se pudo iniciar sesión. Intenta de nuevo.";
}

const NOTICES = {
  expired: "Tu sesión expiró. Inicia sesión de nuevo para continuar.",
  denied: "Tu cuenta no tiene acceso a esta aplicación. Pide a un administrador que te dé de alta.",
} as const;

export const useAuthStore = create<AuthState>((set, get) => {
  async function loadMember(session: Session): Promise<boolean> {
    try {
      const me = await api.getMe();
      set({ status: "signed_in", session, me });
      return true;
    } catch (err) {
      const code = err instanceof api.ApiError ? err.code : null;
      if (code === "not_member") {
        await supabase.auth.signOut();
        set({ status: "signed_out", session: null, me: null, error: NOTICES.denied });
      } else if (code === "session_expired" || code === "invalid_token") {
        await supabase.auth.signOut();
        set({ status: "signed_out", session: null, me: null, notice: NOTICES.expired });
      } else {
        set({
          status: "signed_out",
          session: null,
          me: null,
          error: err instanceof Error ? err.message : "No se pudo comprobar tu acceso.",
        });
      }
      return false;
    }
  }

  return {
    status: "loading",
    session: null,
    me: null,
    isSigningIn: false,
    error: null,
    notice: null,

    init: () => {
      if (!isSupabaseConfigured) {
        set({
          status: "signed_out",
          error: "La autenticación no está configurada (VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY).",
        });
        return () => {};
      }
      supabase.auth.getSession().then(({ data }) => {
        if (data.session) loadMember(data.session);
        else set({ status: "signed_out" });
      });
      const { data } = supabase.auth.onAuthStateChange((event, session) => {
        if (event === "TOKEN_REFRESHED" && session) set({ session });
        if (event === "SIGNED_OUT" && get().status === "signed_in") {
          // signed out elsewhere (another tab) or the refresh token is no longer valid
          set({ status: "signed_out", session: null, me: null, notice: get().notice ?? NOTICES.expired });
        }
      });
      api.setAuthFailureHandler((code) => {
        if (get().status === "signed_in") get().signOut(code === "not_member" ? "denied" : "expired");
      });
      return () => data.subscription.unsubscribe();
    },

    signIn: async (email, password) => {
      set({ isSigningIn: true, error: null, notice: null });
      const { data, error } = await supabase.auth.signInWithPassword({ email: email.trim(), password });
      if (error || !data.session) {
        const reason = error?.message ?? "sin sesión";
        set({ isSigningIn: false, error: signInMessage(reason) });
        api.reportAuthFailure("login_failed", email.trim(), reason);
        return false;
      }
      const ok = await loadMember(data.session);
      set({ isSigningIn: false });
      if (ok) api.reportSessionEvent("login").catch(() => {});
      return ok;
    },

    signOut: async (reason = "user") => {
      const email = get().me?.email ?? "";
      if (reason === "user") {
        await api.reportSessionEvent("logout").catch(() => {});
      } else if (reason === "expired") {
        api.reportAuthFailure("session_expired", email, "la sesión expiró o fue revocada");
      }
      set({
        status: "signed_out",
        session: null,
        me: null,
        notice: reason === "user" ? null : NOTICES[reason],
      });
      await supabase.auth.signOut();
    },

    clearMessages: () => set({ error: null, notice: null }),
  };
});
