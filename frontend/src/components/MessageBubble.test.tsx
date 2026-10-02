import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MessageBubble } from "./MessageBubble";

describe("MessageBubble", () => {
  it("renders user message content", () => {
    render(<MessageBubble message={{ id: "1", role: "user", content: "Hello there" }} />);
    expect(screen.getByText("Hello there")).toBeInTheDocument();
  });

  it("renders a report card with download link when a report is attached", () => {
    render(
      <MessageBubble
        message={{
          id: "2",
          role: "assistant",
          content: "Your report is ready.",
          report: { report_id: "report-1", version: 2, title: "ACME Report", section_count: 6 },
        }}
      />,
    );
    expect(screen.getByText("ACME Report")).toBeInTheDocument();
    expect(screen.getByText("v2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Descargar (.docx)" })).toBeInTheDocument();
  });

  it("applies error styling when the message is flagged as an error", () => {
    render(
      <MessageBubble message={{ id: "3", role: "assistant", content: "Something failed", isError: true }} />,
    );
    expect(screen.getByText("Something failed").className).toContain("bg-danger-subtle");
  });
});
