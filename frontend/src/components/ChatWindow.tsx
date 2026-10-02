import { useEffect, useRef, useState } from "react";
import * as api from "../services/api";
import { useConversationStore } from "../store/useConversationStore";
import type { ChatMessage, Company } from "../types";
import { IconBot, IconSend } from "./icons";
import { MessageBubble } from "./MessageBubble";
import { ProgressStatus } from "./ProgressStatus";
import { Alert } from "./ui/Alert";
import { Spinner } from "./ui/Spinner";

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
        // keep the generic suggestions: the input works without a company name
      });
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [messages, progressMessage]);

  async function submit(content: string) {
    if (!content.trim() || isStreaming) return;
    setInput("");
    await sendUserMessage(content.trim());
  }

  return (
    <div className="flex h-full flex-1 flex-col">
      <div className="flex-1 overflow-y-auto px-4 py-6 sm:px-6">
        <div className="mx-auto flex max-w-3xl flex-col gap-4">
          {isLoadingConversation && (
            <div className="mt-16 flex flex-col items-center gap-2 text-fg-subtle" role="status">
              <Spinner className="h-5 w-5 text-primary" />
              <p className="text-sm">Cargando conversación…</p>
            </div>
          )}
          {!isLoadingConversation && messages.length === 0 && (
            <div className="mt-10 text-center sm:mt-16">
              <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-primary-subtle text-primary-subtle-fg">
                <IconBot className="h-6 w-6" aria-hidden="true" />
              </span>
              <p className="mt-4 text-lg font-semibold text-fg">¿Qué informe necesitas?</p>
              <p className="mx-auto mt-1 max-w-md text-sm text-fg-muted">
                Pide un informe, ajusta uno existente o haz preguntas sobre las alarmas. Prueba con:
              </p>
              <div className="mx-auto mt-6 grid max-w-2xl gap-2 sm:grid-cols-2">
                {suggestions.map((prompt) => (
                  <button
                    key={prompt}
                    onClick={() => submit(prompt)}
                    disabled={isStreaming}
                    className="rounded-xl border border-line bg-surface px-4 py-3 text-left text-sm text-fg shadow-card transition-colors hover:border-primary/50 hover:bg-primary-subtle/40 disabled:opacity-40"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          )}
          {!isLoadingConversation && messages.map((m) => <MessageBubble key={m.id} message={m} />)}
          {isStreaming && progressMessage && <ProgressStatus message={progressMessage} />}
          {error && <Alert tone="danger">{error}</Alert>}
          <div ref={bottomRef} />
        </div>
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit(input);
        }}
        className="border-t border-line bg-surface p-3 sm:p-4"
      >
        <div className="mx-auto flex max-w-3xl items-end gap-2">
          <label className="sr-only" htmlFor="chat-input">
            Mensaje
          </label>
          <textarea
            id="chat-input"
            value={input}
            rows={1}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit(input);
              }
            }}
            placeholder="Describe el informe o haz una pregunta… (Enter para enviar)"
            aria-label="Mensaje"
            className="field-input max-h-40 min-h-[42px] flex-1 resize-none rounded-xl py-2.5"
            disabled={isStreaming}
          />
          <button
            type="submit"
            disabled={isStreaming || !input.trim()}
            aria-label="Enviar"
            className="flex h-[42px] items-center gap-1.5 rounded-xl bg-primary px-4 text-sm font-medium text-primary-fg transition-colors hover:bg-primary-hover disabled:opacity-40"
          >
            {isStreaming ? <Spinner className="h-4 w-4" /> : <IconSend className="h-4 w-4" aria-hidden="true" />}
            <span className="hidden sm:inline">Enviar</span>
          </button>
        </div>
      </form>
    </div>
  );
}
