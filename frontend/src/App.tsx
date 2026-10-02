import { useEffect, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { IconShield } from "./components/icons";
import { Spinner } from "./components/ui/Spinner";
import { AppShell } from "./layout/AppShell";
import { AssistantPage } from "./pages/AssistantPage";
import { AuditPage } from "./pages/AuditPage";
import { DocsPage } from "./pages/DocsPage";
import { FaqPage } from "./pages/FaqPage";
import { GenerateReportPage } from "./pages/GenerateReportPage";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/LoginPage";
import { ObservabilityPage } from "./pages/ObservabilityPage";
import { ReportsPage } from "./pages/ReportsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SourceSettingsPage } from "./pages/SourceSettingsPage";
import { ForbiddenPage, NotFoundPage } from "./pages/StatusPages";
import { useAuthStore } from "./store/useAuthStore";
import { usePreferencesStore } from "./store/usePreferencesStore";

function FullScreenLoader() {
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-3 bg-canvas" role="status">
      <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-500">
        <IconShield className="h-5 w-5 text-white" aria-hidden="true" />
      </span>
      <span className="flex items-center gap-2 text-sm text-fg-muted">
        <Spinner className="h-4 w-4 text-primary" /> Verificando tu sesión…
      </span>
    </div>
  );
}

/** Route protection: no session -> /login (remembering where the user was going). */
function RequireAuth({ children }: { children: ReactNode }) {
  const status = useAuthStore((s) => s.status);
  const location = useLocation();
  if (status === "loading") return <FullScreenLoader />;
  if (status !== "signed_in") return <Navigate to="/login" replace state={{ from: location.pathname + location.hash }} />;
  return <>{children}</>;
}

/** Admin-only screens (the backend enforces the same rule on every request). */
function RequireAdmin({ children }: { children: ReactNode }) {
  const isAdmin = useAuthStore((s) => s.me?.is_admin);
  return isAdmin ? <>{children}</> : <ForbiddenPage />;
}

export default function App() {
  const init = useAuthStore((s) => s.init);
  const status = useAuthStore((s) => s.status);
  const loadPreferences = usePreferencesStore((s) => s.load);

  useEffect(() => init(), [init]);
  useEffect(() => {
    if (status === "signed_in") loadPreferences();
  }, [status, loadPreferences]);

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<HomePage />} />
        <Route path="informes" element={<ReportsPage />} />
        <Route path="informes/nuevo" element={<GenerateReportPage />} />
        <Route path="asistente" element={<AssistantPage />} />
        <Route path="fuente-de-datos" element={<SourceSettingsPage />} />
        <Route
          path="observabilidad"
          element={
            <RequireAdmin>
              <ObservabilityPage />
            </RequireAdmin>
          }
        />
        <Route
          path="auditoria"
          element={
            <RequireAdmin>
              <AuditPage />
            </RequireAdmin>
          }
        />
        <Route path="faq" element={<FaqPage />} />
        <Route path="documentacion" element={<DocsPage />} />
        <Route path="configuracion" element={<SettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
