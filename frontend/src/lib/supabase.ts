import { createClient, type SupabaseClient } from "@supabase/supabase-js";

// Supabase Auth only: the browser signs in here and sends the session's access token to
// the backend, which performs every data operation (as this user, under RLS). The key is
// the project's PUBLIC publishable/anon key -- never a service-role key.
const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

export const isSupabaseConfigured = Boolean(url && anonKey);

export const supabase: SupabaseClient = createClient(url || "http://localhost.invalid", anonKey || "missing", {
  auth: {
    persistSession: true, // the session survives reloads and new tabs
    autoRefreshToken: true, // access tokens are short-lived; refresh before they expire
    detectSessionInUrl: false,
    storageKey: "ai_report_gen_auth",
  },
});
