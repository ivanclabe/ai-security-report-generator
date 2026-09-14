import { useEffect, useRef, useState } from "react";
import { useConversationStore } from "../store/useConversationStore";
import type { ChatMessage } from "../types";
import { MessageBubble } from "./MessageBubble";
import { ProgressStatus } from "./ProgressStatus";

const EMPTY_MESSAGES: ChatMessage[] = [];

const SUGGESTED_PROMPTS = [
  "Genera un informe de seguridad de THOMAS TGS-TPS para julio de 2026.",
  "Muéstrame solo las alarmas críticas de julio 2026.",
  "Genera un informe ejecutivo enfocado en alarmas de \"Agente desconectado\".",
  "¿Cuáles son las técnicas MITRE ATT&CK más frecuentes este período?",
];

export function ChatWindow() {
  const activeId = useConversationStore((s) => s.activeConversationId);
  const messages = useConversationStore((s) =>
    activeId ? (s.messagesByConversation[activeId] ?? EMPTY_MESSAGES) : EMPTY_MESSAGES,
  );
  const isStreaming = useConversationStore((s) => s.isStreaming);
  const progressMessage = useConversationStore((s) => s.progressMessage);
  const error = useConversationStore((s) => s.error);
  const sendUserMessage = useConversationStore((s) => s.sendUserMessage);

  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, progressMessage]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const content = input.trim();
    if (!content || isStreaming) return;
    setInput("");
    await sendUserMessage(content);
  };

  const handleSuggestionClick = async (prompt: string) => {
    if (isStreaming) return;
    await sendUserMessage(prompt);
  };

  return (
    <div className="flex h-full flex-1 flex-col">
      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto flex max-w-3xl flex-col gap-4">
          {messages.length === 0 && (
            <div className="mt-16 text-center">
              <p className="text-lg font-medium text-slate-400">Generador de Informes de Seguridad IA</p>
              <p className="mt-1 text-sm text-slate-400">
                Describe el informe que necesitas, o prueba una de estas sugerencias:
              </p>
              <div className="mx-auto mt-5 flex max-w-xl flex-wrap justify-center gap-2">
                {SUGGESTED_PROMPTS.map((prompt) => (
                  <button
                    key={prompt}
                    onClick={() => handleSuggestionClick(prompt)}
                    disabled={isStreaming}
                    className="rounded-full border border-slate-300 bg-white px-4 py-2 text-left text-sm text-slate-700 hover:border-slate-400 hover:bg-slate-50 disabled:opacity-40"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m) => (
            <MessageBubble key={m.id} message={m} />
          ))}
          {isStreaming && progressMessage && <ProgressStatus message={progressMessage} />}
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div ref={bottomRef} />
        </div>
      </div>
      <form onSubmit={handleSubmit} className="border-t border-slate-200 bg-white p-4">
        <div className="mx-auto flex max-w-3xl items-center gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Describe el informe de seguridad que necesitas..."
            className="flex-1 rounded-full border border-slate-300 px-4 py-2.5 text-sm outline-none focus:border-slate-500"
            disabled={isStreaming}
          />
          <button
            type="submit"
            disabled={isStreaming || !input.trim()}
            className="rounded-full bg-slate-900 px-5 py-2.5 text-sm font-medium text-white disabled:opacity-40"
          >
            Enviar
          </button>
        </div>
      </form>
    </div>
  );
}
