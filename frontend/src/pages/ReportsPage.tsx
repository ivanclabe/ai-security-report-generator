import { useEffect, useState } from "react";
import { IconFilePlus, IconFolder, IconRefresh } from "../components/icons";
import { RecentReportsTable } from "../components/RecentReportsTable";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { LinkButton } from "../components/ui/LinkButton";
import { Page, PageHeader } from "../components/ui/PageHeader";
import { LoadingBlock } from "../components/ui/Spinner";
import * as api from "../services/api";
import type { RecentReport } from "../types";

export function ReportsPage() {
  const [reports, setReports] = useState<RecentReport[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  async function fetchReports() {
    try {
      setReports(await api.listRecentReports(50));
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudieron cargar los informes.");
      setReports([]);
    }
  }

  function reload() {
    setError(null);
    setReports(null);
    fetchReports();
  }

  useEffect(() => {
    let cancelled = false;
    api
      .listRecentReports(50)
      .then((list) => !cancelled && setReports(list))
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "No se pudieron cargar los informes.");
        setReports([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const visible = (reports ?? []).filter((r) =>
    `${r.title ?? ""} ${r.company ?? ""}`.toLowerCase().includes(filter.trim().toLowerCase()),
  );

  return (
    <Page>
      <PageHeader
        eyebrow="Informes"
        title="Informes generados"
        description="Última versión de cada informe, del formulario o del asistente. Descárgalos o ábrelos para ajustarlos."
        actions={
          <>
            <Button variant="secondary" onClick={reload} icon={<IconRefresh className="h-4 w-4" />}>
              Actualizar
            </Button>
            <LinkButton to="/informes/nuevo" icon={<IconFilePlus className="h-4 w-4" />}>
              Nuevo informe
            </LinkButton>
          </>
        }
      />
      {error && <Alert tone="danger" className="mb-4">{error}</Alert>}
      <Card>
        <div className="border-b border-line p-3">
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filtrar por empresa o título…"
            aria-label="Filtrar informes"
            className="field-input max-w-sm"
          />
        </div>
        {reports === null ? (
          <LoadingBlock label="Cargando informes…" />
        ) : visible.length === 0 ? (
          <EmptyState
            icon={<IconFolder className="h-5 w-5" />}
            title={reports.length ? "Ningún informe coincide con el filtro" : "Aún no hay informes"}
            description={reports.length ? "Prueba con otro nombre de empresa." : "Genera el primero desde el formulario o el asistente."}
            action={
              !reports.length && (
                <LinkButton to="/informes/nuevo" icon={<IconFilePlus className="h-4 w-4" />}>
                  Generar informe
                </LinkButton>
              )
            }
          />
        ) : (
          <RecentReportsTable reports={visible} />
        )}
      </Card>
    </Page>
  );
}
