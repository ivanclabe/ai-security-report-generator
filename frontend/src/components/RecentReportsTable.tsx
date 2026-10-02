import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { formatDateTime } from "../lib/format";
import { reportFilename } from "../lib/reportFiles";
import { downloadReport } from "../services/api";
import { useConversationStore } from "../store/useConversationStore";
import { toast } from "../store/useToastStore";
import type { RecentReport } from "../types";
import { IconDownload, IconMessage } from "./icons";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";

export function RecentReportsTable({ reports, compact = false }: { reports: RecentReport[]; compact?: boolean }) {
  const navigate = useNavigate();
  const selectConversation = useConversationStore((s) => s.selectConversation);
  const [downloading, setDownloading] = useState<string | null>(null);

  async function download(report: RecentReport) {
    setDownloading(report.report_id);
    try {
      await downloadReport(report.report_id, reportFilename(report.title || report.company, report.version, report.format));
    } catch (err) {
      toast(err instanceof Error ? err.message : "No se pudo descargar.", "error");
    } finally {
      setDownloading(null);
    }
  }

  return (
    <div className="overflow-x-auto">
      <table className="table-base">
        <thead>
          <tr>
            <th scope="col">Informe</th>
            {!compact && <th scope="col">Empresa</th>}
            <th scope="col">Generado</th>
            <th scope="col" className="text-right">
              <span className="sr-only">Acciones</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {reports.map((r) => (
            <tr key={r.report_id}>
              <td>
                <p className="font-medium">{r.title || "Informe de seguridad"}</p>
                <p className="mt-0.5 flex items-center gap-1.5 text-xs text-fg-subtle">
                  <Badge tone="primary">v{r.version}</Badge> .{r.format} · {r.section_count} secciones
                  {compact && r.company ? ` · ${r.company}` : ""}
                </p>
              </td>
              {!compact && <td className="text-fg-muted">{r.company || "—"}</td>}
              <td className="whitespace-nowrap text-fg-muted">{formatDateTime(r.created_at)}</td>
              <td>
                <div className="flex justify-end gap-1.5">
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`Abrir en el asistente: ${r.title || r.company}`}
                    title="Abrir en el asistente"
                    onClick={async () => {
                      await selectConversation(r.conversation_id);
                      navigate("/asistente");
                    }}
                    icon={<IconMessage className="h-3.5 w-3.5" />}
                  >
                    {!compact && "Abrir"}
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={downloading === r.report_id}
                    onClick={() => download(r)}
                    icon={<IconDownload className="h-3.5 w-3.5" />}
                    aria-label={`Descargar ${r.title || r.company}`}
                  >
                    Descargar
                  </Button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
