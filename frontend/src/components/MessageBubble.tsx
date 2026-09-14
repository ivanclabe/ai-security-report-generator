import type { ChatMessage } from "../types";
import { ReportCard } from "./ReportCard";

export function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex w-full ${isUser ? "justify-end" : "justify-start"}`}>
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
    </div>
  );
}
