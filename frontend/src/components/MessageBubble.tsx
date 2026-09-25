import type { ChatMessage } from "../types";
import { IconAlertCircle, IconBot, IconUser } from "./icons";
import { ReportCard } from "./ReportCard";

export function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex w-full items-start gap-2.5 ${isUser ? "justify-end" : "justify-start"}`}>
      {!isUser && (
        <span
          className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${
            message.isError ? "bg-red-100 text-red-600" : "bg-brand-500 text-white"
          }`}
          aria-hidden="true"
        >
          {message.isError ? <IconAlertCircle className="h-4 w-4" /> : <IconBot className="h-4 w-4" />}
        </span>
      )}
      <div className={`flex max-w-2xl flex-col ${isUser ? "items-end" : "items-start"}`}>
        <div
          className={`whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm ${
            isUser
              ? "bg-slate-900 text-white"
              : message.isError
                ? "bg-red-50 text-red-700"
                : "bg-white text-slate-800 shadow-sm ring-1 ring-slate-200"
          }`}
        >
          {message.content}
        </div>
        {message.report && <ReportCard report={message.report} />}
      </div>
      {isUser && (
        <span
          className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-200 text-slate-600"
          aria-hidden="true"
        >
          <IconUser className="h-4 w-4" />
        </span>
      )}
    </div>
  );
}
