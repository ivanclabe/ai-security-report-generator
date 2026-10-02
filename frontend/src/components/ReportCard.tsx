import { useState } from "react";
import { reportFilename } from "../lib/reportFiles";
import { downloadReport } from "../services/api";
import { useConversationStore } from "../store/useConversationStore";
import { toast } from "../store/useToastStore";
import type { ReportInfo } from "../types";
import { IconDownload, IconFileText } from "./icons";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";

const QUICK_ACTIONS = [
  "Hazlo más ejecutivo.",
  "Hazlo más técnico.",
  "Analiza las tendencias de este período.",
  "Compáralo con el período anterior.",
];

export function ReportCard({ report, showQuickActions = true }: { report: ReportInfo; showQuickActions?: boolean }) {
  const [isDownloading, setIsDownloading] = useState(false);
  const sendUserMessage = useConversationStore((s) => s.sendUserMessage);
  const isStreaming = useConversationStore((s) => s.isStreaming);
  const extension = report.format === "pdf" ? "pdf" : "docx";

  async function handleDownload() {
    setIsDownloading(true);
    try {
      await downloadReport(report.report_id, reportFilename(report.title, report.version, report.format));
    } catch (err) {
      toast(err instanceof Error ? err.message : "No se pudo descargar el informe.", "error");
    } finally {
      setIsDownloading(false);
    }
  }

  return (
    <div className="mt-3 w-full max-w-md rounded-xl border border-line bg-surface p-4 shadow-card">
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary-subtle text-primary-subtle-fg">
          <IconFileText className="h-4 w-4" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <p className="text-sm font-semibold text-fg">{report.title || "Informe de seguridad"}</p>
            <Badge tone="primary">v{report.version}</Badge>
          </div>
          <p className="mt-0.5 text-xs text-fg-subtle">
            {report.section_count} secciones · .{extension}
          </p>
        </div>
      </div>
      {report.objective && <p className="mt-2 line-clamp-2 text-xs text-fg-muted">{report.objective}</p>}
      <Button
        size="sm"
        className="mt-3"
        onClick={handleDownload}
        loading={isDownloading}
        icon={<IconDownload className="h-3.5 w-3.5" aria-hidden="true" />}
      >
        {isDownloading ? "Descargando…" : `Descargar (.${extension})`}
      </Button>

      {showQuickActions && (
        <div className="mt-3 flex flex-wrap gap-1.5 border-t border-line pt-3">
          {QUICK_ACTIONS.map((prompt) => (
            <button
              key={prompt}
              onClick={() => sendUserMessage(prompt)}
              disabled={isStreaming}
              className="rounded-full border border-line px-2.5 py-1 text-[11px] text-fg-muted transition-colors hover:border-primary/50 hover:bg-primary-subtle hover:text-primary-subtle-fg disabled:cursor-not-allowed disabled:opacity-40"
            >
              {prompt}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
