import { useEffect, useState } from "react";
import { ChatWindow } from "./components/ChatWindow";
import { Login } from "./components/Login";
import { ReportForm } from "./components/ReportForm";
import { Sidebar } from "./components/Sidebar";
import { useAuthStore } from "./store/useAuthStore";
import { useConversationStore } from "./store/useConversationStore";

type View = "chat" | "form";

function App() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const loadConversations = useConversationStore((s) => s.loadConversations);
  const [view, setView] = useState<View>("chat");

  useEffect(() => {
    if (isAuthenticated) loadConversations();
  }, [isAuthenticated, loadConversations]);

  if (!isAuthenticated) {
    return <Login />;
  }

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-slate-50">
      <Sidebar />
      <div className="flex h-full flex-1 flex-col overflow-hidden">
        <div className="flex shrink-0 gap-1 border-b border-slate-200 bg-white px-4 pt-2">
          {(["chat", "form"] as const).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={`rounded-t-md px-4 py-2 text-sm font-medium ${
                view === v
                  ? "border border-b-0 border-slate-200 bg-slate-50 text-slate-900"
                  : "text-slate-500 hover:text-slate-800"
              }`}
            >
              {v === "chat" ? "Chat" : "Formulario"}
            </button>
          ))}
        </div>
        <div className="flex-1 overflow-hidden">
          {view === "chat" ? <ChatWindow /> : <div className="h-full overflow-y-auto"><ReportForm /></div>}
        </div>
      </div>
    </div>
  );
}

export default App;
