import { useEffect, useState } from "react";
import { ChatWindow } from "../components/ChatWindow";
import { ConversationList } from "../components/ConversationList";
import { IconMessage } from "../components/icons";
import { useConversationStore } from "../store/useConversationStore";

export function AssistantPage() {
  const loadConversations = useConversationStore((s) => s.loadConversations);
  const conversations = useConversationStore((s) => s.conversations);
  const activeId = useConversationStore((s) => s.activeConversationId);
  const [showList, setShowList] = useState(false);
  const active = conversations.find((c) => c.id === activeId);

  useEffect(() => {
    loadConversations().catch(() => {});
  }, [loadConversations]);

  return (
    <div className="flex h-full">
      <aside
        className={`${showList ? "flex" : "hidden"} w-full shrink-0 flex-col border-r border-line bg-surface md:flex md:w-72`}
        aria-label="Historial de conversaciones"
      >
        <ConversationList onSelect={() => setShowList(false)} />
      </aside>
      <section className={`${showList ? "hidden" : "flex"} min-w-0 flex-1 flex-col md:flex`}>
        <div className="flex items-center gap-2 border-b border-line bg-surface px-4 py-2 md:hidden">
          <button
            onClick={() => setShowList(true)}
            className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-fg-muted hover:bg-surface-2"
          >
            <IconMessage className="h-3.5 w-3.5" aria-hidden="true" />
            Conversaciones
          </button>
          <span className="truncate text-xs text-fg-subtle">{active?.title || ""}</span>
        </div>
        <ChatWindow />
      </section>
    </div>
  );
}
