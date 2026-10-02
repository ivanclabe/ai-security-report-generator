import { useState } from "react";
import { useConversationStore } from "../store/useConversationStore";
import { toast } from "../store/useToastStore";
import { IconEdit, IconMessage, IconPin, IconPlus, IconSearch, IconTrash } from "./icons";
import { Button } from "./ui/Button";
import { Modal } from "./ui/Modal";

export function ConversationList({ onSelect }: { onSelect?: () => void }) {
  const conversations = useConversationStore((s) => s.conversations);
  const activeId = useConversationStore((s) => s.activeConversationId);
  const selectConversation = useConversationStore((s) => s.selectConversation);
  const startNewConversation = useConversationStore((s) => s.startNewConversation);
  const renameConversation = useConversationStore((s) => s.renameConversation);
  const deleteConversation = useConversationStore((s) => s.deleteConversation);
  const togglePinConversation = useConversationStore((s) => s.togglePinConversation);

  const [filter, setFilter] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [pendingDelete, setPendingDelete] = useState<{ id: string; title: string | null } | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const visible = conversations.filter((c) =>
    (c.title || "Conversación sin título").toLowerCase().includes(filter.trim().toLowerCase()),
  );

  async function commitEditing() {
    if (editingId) await renameConversation(editingId, editingTitle);
    setEditingId(null);
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    setIsDeleting(true);
    try {
      await deleteConversation(pendingDelete.id);
      toast("Conversación eliminada.");
    } catch (err) {
      toast(err instanceof Error ? err.message : "No se pudo eliminar.", "error");
    } finally {
      setIsDeleting(false);
      setPendingDelete(null);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="space-y-2 p-3">
        <Button
          className="w-full"
          onClick={async () => {
            await startNewConversation();
            onSelect?.();
          }}
          icon={<IconPlus className="h-4 w-4" aria-hidden="true" />}
        >
          Nueva conversación
        </Button>
        <label className="relative block">
          <span className="sr-only">Buscar conversaciones</span>
          <IconSearch className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-fg-subtle" />
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Buscar…"
            className="field-input h-8 pl-8 text-xs"
          />
        </label>
      </div>
      <nav aria-label="Conversaciones" className="flex-1 overflow-y-auto px-2 pb-3">
        {visible.length === 0 && (
          <p className="px-3 py-6 text-center text-xs text-fg-subtle">
            {conversations.length === 0 ? "Aún no hay conversaciones." : "Sin resultados."}
          </p>
        )}
        {visible.map((c) => (
          <div
            key={c.id}
            className={`group mb-0.5 flex w-full items-center rounded-lg text-sm ${
              c.id === activeId ? "bg-primary-subtle font-medium text-primary-subtle-fg" : "text-fg-muted hover:bg-surface-2"
            }`}
          >
            {editingId === c.id ? (
              <input
                autoFocus
                aria-label="Nuevo título"
                value={editingTitle}
                onChange={(e) => setEditingTitle(e.target.value)}
                onBlur={commitEditing}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commitEditing();
                  if (e.key === "Escape") setEditingId(null);
                }}
                className="field-input my-1 ml-2 mr-2 h-8 flex-1"
              />
            ) : (
              <>
                <button
                  onClick={() => {
                    selectConversation(c.id);
                    onSelect?.();
                  }}
                  aria-current={c.id === activeId ? "true" : undefined}
                  className="flex min-w-0 flex-1 items-center gap-2 px-3 py-2 text-left"
                >
                  {c.is_pinned ? (
                    <IconPin className="h-3.5 w-3.5 shrink-0 text-primary" aria-label="Anclada" />
                  ) : (
                    <IconMessage className="h-3.5 w-3.5 shrink-0 opacity-60" aria-hidden="true" />
                  )}
                  <span className="truncate">{c.title || "Conversación sin título"}</span>
                </button>
                <div className="flex shrink-0 items-center opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
                  <button
                    onClick={() => togglePinConversation(c.id)}
                    aria-label={c.is_pinned ? "Desanclar conversación" : "Anclar conversación"}
                    className="rounded p-1.5 text-fg-subtle hover:bg-surface-3 hover:text-fg"
                  >
                    <IconPin className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={() => {
                      setEditingId(c.id);
                      setEditingTitle(c.title ?? "");
                    }}
                    aria-label="Renombrar conversación"
                    className="rounded p-1.5 text-fg-subtle hover:bg-surface-3 hover:text-fg"
                  >
                    <IconEdit className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={() => setPendingDelete({ id: c.id, title: c.title })}
                    aria-label="Eliminar conversación"
                    className="mr-1 rounded p-1.5 text-fg-subtle hover:bg-danger-subtle hover:text-danger"
                  >
                    <IconTrash className="h-3.5 w-3.5" />
                  </button>
                </div>
              </>
            )}
          </div>
        ))}
      </nav>

      {pendingDelete && (
        <Modal
          title="¿Eliminar la conversación?"
          description={`«${pendingDelete.title || "Conversación sin título"}» y sus informes asociados se eliminarán. Esta acción no se puede deshacer.`}
          onClose={() => !isDeleting && setPendingDelete(null)}
          footer={
            <>
              <Button variant="secondary" onClick={() => setPendingDelete(null)} disabled={isDeleting}>
                Cancelar
              </Button>
              <Button variant="danger" onClick={confirmDelete} loading={isDeleting}>
                Eliminar
              </Button>
            </>
          }
        >
          <p className="text-sm text-fg-muted">La eliminación queda registrada en la auditoría.</p>
        </Modal>
      )}
    </div>
  );
}
