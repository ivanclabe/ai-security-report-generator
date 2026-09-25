import { useState } from "react";
import { downloadReport } from "../services/api";
import { useConversationStore } from "../store/useConversationStore";
import type { ReportInfo } from "../types";
import { IconDownload } from "./icons";

const QUICK_ACTIONS = [
  "Hazlo más ejecutivo.",
  "Hazlo más técnico.",
  "Analiza las tendencias de este período.",
  "Compáralo con el período anterior.",
];

export function ReportCard({
  report,
  showQuickActions = true,
}: {
  report: ReportInfo;
  showQuickActions?: boolean;
}) {
  const [isDownloading, setIsDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sendUserMessage = useConversationStore((s) => s.sendUserMessage);
  const isStreaming = useConversationStore((s) => s.isStreaming);

  const extension = report.format === "pdf" ? "pdf" : "docx";

  async function handleDownload() {
    setIsDownloading(true);
    setError(null);
    try {
      const filename = `${report.title || "informe-de-seguridad"}-v${report.version}.${extension}`.replace(
        /\s+/g,
        "-",
      );
      await downloadReport(report.report_id, filename);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo descargar el informe.");
    } finally {
      setIsDownloading(false);
    }
  }

  return (
    <div className="mt-3 w-full max-w-md rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold text-slate-900">{report.title || "Informe de Seguridad"}</p>
        <span className="rounded-full bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-700">
          v{report.version}
        </span>
      </div>
      <p className="mt-1 text-xs text-slate-500">{report.section_count} secciones</p>
      {report.objective && <p className="mt-2 text-xs text-slate-600 line-clamp-2">{report.objective}</p>}
      <button
        onClick={handleDownload}
        disabled={isDownloading}
        className="mt-3 inline-flex items-center gap-1.5 rounded-md bg-brand-500 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-brand-600 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <IconDownload className="h-3.5 w-3.5" aria-hidden="true" />
        {isDownloading ? "Descargando..." : `Descargar Informe (.${extension})`}
      </button>
      {error && (
        <p role="alert" className="mt-2 text-xs text-red-600">
          {error}
        </p>
      )}

      {showQuickActions && (
        <div className="mt-3 flex flex-wrap gap-1.5 border-t border-slate-100 pt-3">
          {QUICK_ACTIONS.map((prompt) => (
            <button
              key={prompt}
              onClick={() => sendUserMessage(prompt)}
              disabled={isStreaming}
              className="rounded-full border border-slate-200 px-2.5 py-1 text-[11px] text-slate-600 transition-colors hover:border-brand-400 hover:bg-brand-50 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {prompt}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
