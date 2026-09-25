import { useEffect, useRef, useState } from "react";
import * as api from "../services/api";
import { useConversationStore } from "../store/useConversationStore";
import type { ChatMessage, Company } from "../types";
import { IconFileText, IconSend } from "./icons";
import { MessageBubble } from "./MessageBubble";
import { ProgressStatus } from "./ProgressStatus";

const EMPTY_MESSAGES: ChatMessage[] = [];

function buildSuggestions(company: Company | undefined): string[] {
  const name = company?.name ?? "tu empresa";
  return [
    `Genera un informe de seguridad de ${name} para el mes pasado.`,
    "Muéstrame solo las alarmas críticas del período.",
    'Genera un informe ejecutivo enfocado en alarmas de "Agente desconectado".',
    "¿Cuáles son las técnicas MITRE ATT&CK más frecuentes este período?",
  ];
}

export function ChatWindow() {
  const activeId = useConversationStore((s) => s.activeConversationId);
  const messages = useConversationStore((s) =>
    activeId ? (s.messagesByConversation[activeId] ?? EMPTY_MESSAGES) : EMPTY_MESSAGES,
  );
  const isStreaming = useConversationStore((s) => s.isStreaming);
  const isLoadingConversation = useConversationStore((s) => s.isLoadingConversation);
  const progressMessage = useConversationStore((s) => s.progressMessage);
  const error = useConversationStore((s) => s.error);
  const sendUserMessage = useConversationStore((s) => s.sendUserMessage);

  const [input, setInput] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>(buildSuggestions(undefined));
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api
      .listCompanies()
      .then((companies) => setSuggestions(buildSuggestions(companies[0])))
      .catch(() => {
        // Keep the generic fallback suggestions -- the input still works fine
        // without a company to name in the example prompt.
      });
  }, []);

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
          {isLoadingConversation && (
            <div className="mt-16 flex flex-col items-center gap-2 text-slate-400" role="status">
              <span className="h-5 w-5 animate-spin rounded-full border-2 border-slate-300 border-t-brand-500" />
              <p className="text-sm">Cargando conversación...</p>
            </div>
          )}
          {!isLoadingConversation && messages.length === 0 && (
            <div className="mt-16 text-center">
              <IconFileText className="mx-auto h-8 w-8 text-slate-300" aria-hidden="true" />
              <p className="mt-3 text-lg font-medium text-slate-400">Generador de Informes de Seguridad IA</p>
              <p className="mt-1 text-sm text-slate-400">
                Describe el informe que necesitas, o prueba una de estas sugerencias:
              </p>
              <div className="mx-auto mt-5 flex max-w-xl flex-wrap justify-center gap-2">
                {suggestions.map((prompt) => (
                  <button
                    key={prompt}
                    onClick={() => handleSuggestionClick(prompt)}
                    disabled={isStreaming}
                    className="rounded-full border border-slate-300 bg-white px-4 py-2 text-left text-sm text-slate-700 transition-colors hover:border-brand-400 hover:bg-brand-50 disabled:opacity-40"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          )}
          {!isLoadingConversation && messages.map((m) => <MessageBubble key={m.id} message={m} />)}
          {isStreaming && progressMessage && <ProgressStatus message={progressMessage} />}
          {error && (
            <p role="alert" className="text-sm text-red-600">
              {error}
            </p>
          )}
          <div ref={bottomRef} />
        </div>
      </div>
      <form onSubmit={handleSubmit} className="border-t border-slate-200 bg-white p-4">
        <div className="mx-auto flex max-w-3xl items-center gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Describe el informe de seguridad que necesitas..."
            aria-label="Mensaje"
            className="flex-1 rounded-full border border-slate-300 px-4 py-2.5 text-sm outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
            disabled={isStreaming}
          />
          <button
            type="submit"
            disabled={isStreaming || !input.trim()}
            aria-label="Enviar"
            className="flex items-center gap-1.5 rounded-full bg-brand-500 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-brand-600 disabled:opacity-40"
          >
            Enviar
            <IconSend className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
      </form>
    </div>
  );
}
