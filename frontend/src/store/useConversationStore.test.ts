import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StreamEvent } from "../types";

vi.mock("../services/api", () => ({
  createConversation: vi.fn(async () => ({ id: "conv-1", title: null, created_at: "now" })),
  listConversations: vi.fn(async () => []),
  getConversation: vi.fn(async () => ({ id: "conv-1", title: null, created_at: "now", messages: [] })),
  sendMessage: vi.fn(
    async (_id: string, _content: string, onEvent: (e: StreamEvent) => void) => {
      onEvent({ event: "progress", node: "understand_request", message: "Understanding request..." });
      onEvent({
        event: "result",
        status: "ready",
        message: "Your report is ready.",
        errors: [],
        report: { report_id: "report-1", version: 1, title: "ACME Report", section_count: 5 },
      });
    },
  ),
  downloadUrl: vi.fn((id: string) => `/api/reports/${id}/download`),
}));

import { useConversationStore } from "./useConversationStore";

describe("useConversationStore.sendUserMessage", () => {
  beforeEach(() => {
    useConversationStore.setState({
      conversations: [],
      activeConversationId: null,
      messagesByConversation: {},
      latestReportByConversation: {},
      isStreaming: false,
      progressMessage: null,
      error: null,
    });
  });

  it("creates a conversation on first send, then appends user + assistant messages with the report", async () => {
    await useConversationStore.getState().sendUserMessage("Generate a report for ACME.");

    const state = useConversationStore.getState();
    expect(state.activeConversationId).toBe("conv-1");
    const messages = state.messagesByConversation["conv-1"];
    expect(messages).toHaveLength(2);
    expect(messages[0]).toMatchObject({ role: "user", content: "Generate a report for ACME." });
    expect(messages[1]).toMatchObject({ role: "assistant", content: "Your report is ready." });
    expect(messages[1].report?.report_id).toBe("report-1");
    expect(state.latestReportByConversation["conv-1"]?.version).toBe(1);
    expect(state.isStreaming).toBe(false);
  });
});
