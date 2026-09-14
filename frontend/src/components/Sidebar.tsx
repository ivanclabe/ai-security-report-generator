import { useState } from "react";
import { useAuthStore } from "../store/useAuthStore";
import { useConversationStore } from "../store/useConversationStore";

export function Sidebar() {
  const conversations = useConversationStore((s) => s.conversations);
  const activeId = useConversationStore((s) => s.activeConversationId);
  const selectConversation = useConversationStore((s) => s.selectConversation);
  const startNewConversation = useConversationStore((s) => s.startNewConversation);
  const renameConversation = useConversationStore((s) => s.renameConversation);
  const deleteConversation = useConversationStore((s) => s.deleteConversation);
  const togglePinConversation = useConversationStore((s) => s.togglePinConversation);
  const username = useAuthStore((s) => s.username);
  const logout = useAuthStore((s) => s.logout);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");

  function startEditing(id: string, currentTitle: string | null) {
    setEditingId(id);
    setEditingTitle(currentTitle ?? "");
  }

  async function commitEditing() {
    if (editingId) {
      await renameConversation(editingId, editingTitle);
    }
    setEditingId(null);
  }

  async function handleDelete(id: string, title: string | null) {
    const confirmed = window.confirm(
      `¿Eliminar la conversación "${title || "sin título"}"? Esta acción no se puede deshacer.`,
    );
    if (!confirmed) return;
    await deleteConversation(id);
  }

  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-slate-200 bg-white">
      <div className="p-3">
        <button
          onClick={() => startNewConversation()}
          className="w-full rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-700"
        >
          + Nuevo informe
        </button>
      </div>
      <nav className="flex-1 overflow-y-auto px-2 pb-3">
        {conversations.length === 0 && (
          <p className="px-2 py-4 text-sm text-slate-400">Aún no hay conversaciones.</p>
        )}
        {conversations.map((c) => (
          <div
            key={c.id}
            className={`group mb-1 flex w-full items-center rounded-md text-sm ${
              c.id === activeId ? "bg-slate-100 font-medium text-slate-900" : "text-slate-600 hover:bg-slate-50"
            }`}
          >
            {editingId === c.id ? (
              <input
                autoFocus
                value={editingTitle}
                onChange={(e) => setEditingTitle(e.target.value)}
                onBlur={commitEditing}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commitEditing();
                  if (e.key === "Escape") setEditingId(null);
                }}
                className="my-1 ml-3 mr-2 flex-1 rounded border border-slate-300 px-1 py-1 text-sm text-slate-900 focus:outline-none focus:ring-1 focus:ring-slate-400"
              />
            ) : (
              <>
                <button
                  onClick={() => selectConversation(c.id)}
                  className="flex-1 truncate px-3 py-2 text-left"
                >
                  {c.is_pinned && <span className="mr-1">📌</span>}
                  {c.title || "Conversación sin título"}
                </button>
                <button
                  onClick={() => togglePinConversation(c.id)}
                  title={c.is_pinned ? "Desanclar" : "Anclar"}
                  className={`shrink-0 px-1.5 hover:text-slate-700 ${
                    c.is_pinned ? "block text-slate-500" : "hidden text-slate-400 group-hover:block"
                  }`}
                >
                  📌
                </button>
                <button
                  onClick={() => startEditing(c.id, c.title)}
                  title="Renombrar"
                  className="hidden shrink-0 px-1.5 text-slate-400 hover:text-slate-700 group-hover:block"
                >
                  ✎
                </button>
                <button
                  onClick={() => handleDelete(c.id, c.title)}
                  title="Eliminar"
                  className="hidden shrink-0 px-1.5 pr-2 text-slate-400 hover:text-red-600 group-hover:block"
                >
                  ✕
                </button>
              </>
            )}
          </div>
        ))}
      </nav>
      <div className="flex items-center justify-between border-t border-slate-200 px-3 py-2">
        <span className="truncate text-xs text-slate-500">{username}</span>
        <button onClick={logout} className="text-xs font-medium text-slate-500 hover:text-slate-800">
          Cerrar sesión
        </button>
      </div>
    </aside>
  );
}
