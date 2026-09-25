import { useEffect, useState } from "react";
import { ChatWindow } from "./components/ChatWindow";
import { IconFileText, IconMenu } from "./components/icons";
import { Login } from "./components/Login";
import { ReportForm } from "./components/ReportForm";
import { Sidebar } from "./components/Sidebar";
import { useAuthStore } from "./store/useAuthStore";
import { useConversationStore } from "./store/useConversationStore";

type View = "chat" | "form";

const VIEWS: { key: View; label: string }[] = [
  { key: "chat", label: "Chat" },
  { key: "form", label: "Formulario" },
];

function App() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const loadConversations = useConversationStore((s) => s.loadConversations);
  const [view, setView] = useState<View>("chat");
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  useEffect(() => {
    if (isAuthenticated) loadConversations();
  }, [isAuthenticated, loadConversations]);

  if (!isAuthenticated) {
    return <Login />;
  }

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-slate-50">
      {/* Off-canvas on narrow screens (below lg): a fixed drawer + backdrop,
          toggled by the header's menu button. Static/always-visible on lg+,
          where the sidebar has room to sit alongside the content. */}
      {isSidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-slate-900/30 lg:hidden"
          onClick={() => setIsSidebarOpen(false)}
          aria-hidden="true"
        />
      )}
      <div
        className={`fixed inset-y-0 left-0 z-40 transition-transform lg:static lg:translate-x-0 ${
          isSidebarOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <Sidebar onNavigate={() => setIsSidebarOpen(false)} />
      </div>

      <div className="flex h-full flex-1 flex-col overflow-hidden">
        <header className="flex shrink-0 items-center justify-between border-b border-slate-200 bg-white px-4 py-3 sm:px-6">
          <div className="flex items-center gap-2">
            <button
              onClick={() => setIsSidebarOpen(true)}
              aria-label="Abrir menú de conversaciones"
              className="-ml-1 rounded-md p-1.5 text-slate-500 hover:bg-slate-100 lg:hidden"
            >
              <IconMenu className="h-5 w-5" />
            </button>
            <IconFileText className="hidden h-5 w-5 shrink-0 text-brand-500 sm:block" aria-hidden="true" />
            <div className="min-w-0">
              <h1 className="truncate text-sm font-semibold text-slate-900">
                Generador de Informes de Seguridad
              </h1>
              <p className="hidden text-xs text-slate-400 sm:block">Centro de Operaciones de Seguridad</p>
            </div>
          </div>

          <div role="tablist" aria-label="Modalidad de generación" className="flex shrink-0 rounded-lg bg-slate-100 p-1">
            {VIEWS.map((v) => (
              <button
                key={v.key}
                role="tab"
                aria-selected={view === v.key}
                onClick={() => setView(v.key)}
                className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors sm:px-4 ${
                  view === v.key
                    ? "bg-white text-slate-900 shadow-sm"
                    : "text-slate-500 hover:text-slate-800"
                }`}
              >
                {v.label}
              </button>
            ))}
          </div>
        </header>
        <div className="flex-1 overflow-hidden" role="tabpanel">
          {view === "chat" ? <ChatWindow /> : <div className="h-full overflow-y-auto"><ReportForm /></div>}
        </div>
      </div>
    </div>
  );
}

export default App;
