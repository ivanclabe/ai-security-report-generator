import { create } from "zustand";
import * as api from "../services/api";
import type { ChatMessage, ConversationSummary, LLMRunInfo, ReportInfo } from "../types";
import { useLLMStore } from "./useLLMStore";

interface ConversationState {
  conversations: ConversationSummary[];
  activeConversationId: string | null;
  messagesByConversation: Record<string, ChatMessage[]>;
  latestReportByConversation: Record<string, ReportInfo | null>;
  isStreaming: boolean;
  progressMessage: string | null;
  /** Provider/model answering the current turn (updated live on a fallback). */
  llmRun: LLMRunInfo | null;
  error: string | null;
  isLoadingConversation: boolean;

  loadConversations: () => Promise<void>;
  startNewConversation: () => Promise<void>;
  selectConversation: (id: string) => Promise<void>;
  sendUserMessage: (content: string) => Promise<void>;
  renameConversation: (id: string, title: string) => Promise<void>;
  deleteConversation: (id: string) => Promise<void>;
  togglePinConversation: (id: string) => Promise<void>;
}

let messageCounter = 0;
function nextLocalId(prefix: string) {
  messageCounter += 1;
  return `${prefix}-local-${messageCounter}`;
}

function sortConversations(list: ConversationSummary[]): ConversationSummary[] {
  return [...list].sort((a, b) => {
    if (a.is_pinned !== b.is_pinned) return a.is_pinned ? -1 : 1;
    return a.created_at < b.created_at ? 1 : a.created_at > b.created_at ? -1 : 0;
  });
}

export const useConversationStore = create<ConversationState>((set, get) => ({
  conversations: [],
  activeConversationId: null,
  messagesByConversation: {},
  latestReportByConversation: {},
  isStreaming: false,
  progressMessage: null,
  llmRun: null,
  error: null,
  isLoadingConversation: false,

  loadConversations: async () => {
    const conversations = await api.listConversations();
    set({ conversations: sortConversations(conversations) });
    if (!get().activeConversationId && conversations.length > 0) {
      await get().selectConversation(conversations[0].id);
    }
  },

  startNewConversation: async () => {
    const conversation = await api.createConversation();
    set((state) => ({
      conversations: sortConversations([conversation, ...state.conversations]),
      activeConversationId: conversation.id,
      messagesByConversation: { ...state.messagesByConversation, [conversation.id]: [] },
      latestReportByConversation: { ...state.latestReportByConversation, [conversation.id]: null },
    }));
  },

  selectConversation: async (id: string) => {
    set({ activeConversationId: id });
    if (get().messagesByConversation[id]) return;
    set({ isLoadingConversation: true });
    const detail = await api.getConversation(id).finally(() => set({ isLoadingConversation: false }));
    const messages: ChatMessage[] = detail.messages.map((m) => ({
      id: m.id,
      role: m.role,
      content: m.content,
    }));
    // Reattach the report card to the last assistant message so reopening a
    // conversation (or reloading the page) shows the same download card it
    // showed live -- history previously lost it entirely (Fase 6).
    if (detail.report) {
      for (let i = messages.length - 1; i >= 0; i--) {
        if (messages[i].role === "assistant") {
          messages[i] = { ...messages[i], report: detail.report };
          break;
        }
      }
    }
    set((state) => ({
      messagesByConversation: { ...state.messagesByConversation, [id]: messages },
      latestReportByConversation: { ...state.latestReportByConversation, [id]: detail.report },
    }));
  },

  sendUserMessage: async (content: string) => {
    let conversationId = get().activeConversationId;
    if (!conversationId) {
      await get().startNewConversation();
      conversationId = get().activeConversationId;
    }
    if (!conversationId) return;
    const id = conversationId;

    const userMessage: ChatMessage = { id: nextLocalId("user"), role: "user", content };
    set((state) => ({
      messagesByConversation: {
        ...state.messagesByConversation,
        [id]: [...(state.messagesByConversation[id] ?? []), userMessage],
      },
      isStreaming: true,
      progressMessage: "Comprobando el proveedor de IA…",
      llmRun: null,
      error: null,
    }));

    try {
      await api.sendMessage(id, content, (event) => {
        if (event.event === "llm") {
          set({ llmRun: event });
        } else if (event.event === "progress") {
          set({ progressMessage: event.message });
        } else if (event.event === "result") {
          const assistantMessage: ChatMessage = {
            id: nextLocalId("assistant"),
            role: "assistant",
            content: event.message,
            report: event.report,
            isError: event.status === "error",
            errorCode: event.error_code ?? null,
            llm: event.llm ?? null,
          };
          set((state) => ({
            messagesByConversation: {
              ...state.messagesByConversation,
              [id]: [...(state.messagesByConversation[id] ?? []), assistantMessage],
            },
            latestReportByConversation: event.report
              ? { ...state.latestReportByConversation, [id]: event.report }
              : state.latestReportByConversation,
          }));
        }
      }, undefined, useLLMStore.getState().selection);
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Algo salió mal. Intenta de nuevo." });
    } finally {
      set({ isStreaming: false, progressMessage: null });
    }
  },

  renameConversation: async (id: string, title: string) => {
    const trimmed = title.trim();
    if (!trimmed) return;
    const updated = await api.renameConversation(id, trimmed);
    set((state) => ({
      conversations: sortConversations(state.conversations.map((c) => (c.id === id ? updated : c))),
    }));
  },

  togglePinConversation: async (id: string) => {
    const current = get().conversations.find((c) => c.id === id);
    if (!current) return;
    const updated = await api.setConversationPinned(id, !current.is_pinned);
    set((state) => ({
      conversations: sortConversations(state.conversations.map((c) => (c.id === id ? updated : c))),
    }));
  },

  deleteConversation: async (id: string) => {
    await api.deleteConversation(id);
    set((state) => {
      const conversations = state.conversations.filter((c) => c.id !== id);
      const messagesByConversation = { ...state.messagesByConversation };
      delete messagesByConversation[id];
      const latestReportByConversation = { ...state.latestReportByConversation };
      delete latestReportByConversation[id];
      const wasActive = state.activeConversationId === id;
      return {
        conversations,
        messagesByConversation,
        latestReportByConversation,
        activeConversationId: wasActive
          ? (conversations[0]?.id ?? null)
          : state.activeConversationId,
      };
    });
    const nextActive = get().activeConversationId;
    if (nextActive && !get().messagesByConversation[nextActive]) {
      await get().selectConversation(nextActive);
    }
  },
}));
