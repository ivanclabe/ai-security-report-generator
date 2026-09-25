import { useState } from "react";
import { useAuthStore } from "../store/useAuthStore";
import { useConversationStore } from "../store/useConversationStore";
import { IconEdit, IconLogout, IconPin, IconPlus, IconTrash, IconUser } from "./icons";

export function Sidebar({ onNavigate }: { onNavigate?: () => void } = {}) {
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
    <aside className="flex h-full w-72 shrink-0 flex-col border-r border-slate-200 bg-white shadow-xl lg:shadow-none">
      <div className="p-3">
        <button
          onClick={() => {
            startNewConversation();
            onNavigate?.();
          }}
          className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-brand-500 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-600"
        >
          <IconPlus className="h-4 w-4" aria-hidden="true" />
          Nuevo informe
        </button>
      </div>
      <nav aria-label="Conversaciones" className="flex-1 overflow-y-auto px-2 pb-3">
        {conversations.length === 0 && (
          <p className="px-3 py-4 text-sm text-slate-400">Aún no hay conversaciones.</p>
        )}
        {conversations.map((c) => (
          <div
            key={c.id}
            className={`group mb-1 flex w-full items-center rounded-md text-sm ${
              c.id === activeId ? "bg-brand-50 font-medium text-brand-700" : "text-slate-600 hover:bg-slate-50"
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
                className="my-1 ml-3 mr-2 flex-1 rounded border border-slate-300 px-1.5 py-1 text-sm text-slate-900 outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
              />
            ) : (
              <>
                <button
                  onClick={() => {
                    selectConversation(c.id);
                    onNavigate?.();
                  }}
                  className="flex flex-1 items-center gap-1.5 truncate px-3 py-2 text-left"
                >
                  {c.is_pinned && <IconPin className="h-3.5 w-3.5 shrink-0 text-brand-500" aria-label="Anclada" />}
                  <span className="truncate">{c.title || "Conversación sin título"}</span>
                </button>
                <div className="flex shrink-0 items-center opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
                  <button
                    onClick={() => togglePinConversation(c.id)}
                    aria-label={c.is_pinned ? "Desanclar conversación" : "Anclar conversación"}
                    className={`rounded p-1.5 hover:bg-slate-200 hover:text-slate-700 ${
                      c.is_pinned ? "text-brand-600" : "text-slate-400"
                    }`}
                  >
                    <IconPin className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={() => startEditing(c.id, c.title)}
                    aria-label="Renombrar conversación"
                    className="rounded p-1.5 text-slate-400 hover:bg-slate-200 hover:text-slate-700"
                  >
                    <IconEdit className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={() => handleDelete(c.id, c.title)}
                    aria-label="Eliminar conversación"
                    className="mr-1 rounded p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600"
                  >
                    <IconTrash className="h-3.5 w-3.5" />
                  </button>
                </div>
              </>
            )}
          </div>
        ))}
      </nav>
      <div className="flex items-center justify-between border-t border-slate-200 px-3 py-2.5">
        <span className="flex min-w-0 items-center gap-1.5 text-xs text-slate-500">
          <IconUser className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span className="truncate">{username}</span>
        </span>
        <button
          onClick={logout}
          className="flex shrink-0 items-center gap-1 rounded px-1.5 py-1 text-xs font-medium text-slate-500 hover:bg-slate-100 hover:text-slate-800"
        >
          <IconLogout className="h-3.5 w-3.5" aria-hidden="true" />
          Cerrar sesión
        </button>
      </div>
    </aside>
  );
}
