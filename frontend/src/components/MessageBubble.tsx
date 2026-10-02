import type { ChatMessage } from "../types";
import { IconAlertCircle, IconBot, IconUser } from "./icons";
import { ReportCard } from "./ReportCard";
import { SourceNotConfiguredNotice } from "./SourceNotConfiguredNotice";

export function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex w-full items-start gap-2.5 ${isUser ? "justify-end" : "justify-start"}`}>
      {!isUser && (
        <span
          className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${
            message.isError ? "bg-danger-subtle text-danger" : "bg-primary text-primary-fg"
          }`}
          aria-hidden="true"
        >
          {message.isError ? <IconAlertCircle className="h-4 w-4" /> : <IconBot className="h-4 w-4" />}
        </span>
      )}
      <div className={`flex max-w-2xl flex-col ${isUser ? "items-end" : "items-start"}`}>
        <div
          className={`whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
            isUser
              ? "rounded-tr-md bg-primary text-primary-fg"
              : message.isError
                ? "rounded-tl-md border border-danger/25 bg-danger-subtle text-danger-fg"
                : "rounded-tl-md border border-line bg-surface text-fg shadow-card"
          }`}
        >
          {message.content}
        </div>
        {message.errorCode === "source_not_configured" && (
          <div className="mt-2 w-full">
            <SourceNotConfiguredNotice compact />
          </div>
        )}
        {message.llm && !isUser && (
          <p className="mt-1 text-[11px] text-fg-subtle" title={`Proveedor solicitado: ${message.llm.requested_label}`}>
            {message.llm.provider_label} · {message.llm.model}
            {message.llm.switched && message.llm.last_fallback ? ` (tras cambio por ${message.llm.last_fallback.reason_label.toLowerCase()})` : ""}
          </p>
        )}
        {message.report && <ReportCard report={message.report} />}
      </div>
      {isUser && (
        <span
          className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-surface-3 text-fg-muted"
          aria-hidden="true"
        >
          <IconUser className="h-4 w-4" />
        </span>
      )}
    </div>
  );
}
