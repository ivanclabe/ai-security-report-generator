import { Fragment, useEffect, useState } from "react";
import { IconChevronDown, IconChevronRight, IconClipboard, IconDownload, IconSearch } from "../components/icons";
import { Alert } from "../components/ui/Alert";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { Page, PageHeader } from "../components/ui/PageHeader";
import { LoadingBlock } from "../components/ui/Spinner";
import { ACTION_LABELS, MODULE_LABELS, RESULT_LABELS, formatDateTime } from "../lib/format";
import * as api from "../services/api";
import { toast } from "../store/useToastStore";
import type { AuditFilters, AuditPage as AuditPageData } from "../types";

const PAGE_SIZE = 50;
const ACTION_GROUPS = [
  { value: "", label: "Todas las acciones" },
  { value: "auth", label: "Autenticación" },
  { value: "source", label: "Fuente de datos" },
  { value: "report", label: "Informes" },
  { value: "agent", label: "Asistente" },
  { value: "settings", label: "Preferencias" },
  { value: "audit", label: "Auditoría" },
];

export function AuditPage() {
  const [filters, setFilters] = useState<AuditFilters>({});
  const [debounced, setDebounced] = useState<AuditFilters>({});
  const [offset, setOffset] = useState(0);
  // Results are tagged with the query they answer: while the current query has no
  // result yet, the table shows the loading state (no synchronous reset needed).
  const [result, setResult] = useState<{ key: string; page: AuditPageData | null; error: string | null } | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [isExporting, setIsExporting] = useState(false);

  useEffect(() => {
    const t = window.setTimeout(() => {
      setDebounced(filters);
      setOffset(0);
    }, 300);
    return () => window.clearTimeout(t);
  }, [filters]);

  const queryKey = JSON.stringify([debounced, offset]);
  useEffect(() => {
    let cancelled = false;
    api
      .listAudit(debounced, PAGE_SIZE, offset)
      .then((page) => !cancelled && setResult({ key: queryKey, page, error: null }))
      .catch(
        (err) =>
          !cancelled &&
          setResult({ key: queryKey, page: null, error: err instanceof Error ? err.message : "No se pudo cargar la auditoría." }),
      );
    return () => {
      cancelled = true;
    };
  }, [debounced, offset, queryKey]);

  const current = result?.key === queryKey ? result : null;
  const page = current?.page ?? null;
  const error = current?.error ?? null;

  const set = (key: keyof AuditFilters, value: string) => setFilters((f) => ({ ...f, [key]: value || undefined }));
  const total = page?.total ?? 0;
  const hasFilters = Object.values(filters).some(Boolean);

  async function exportCsv() {
    setIsExporting(true);
    try {
      await api.exportAudit(debounced);
      toast("Exportación descargada (también quedó registrada en la auditoría).");
    } catch (err) {
      toast(err instanceof Error ? err.message : "No se pudo exportar.", "error");
    } finally {
      setIsExporting(false);
    }
  }

  return (
    <Page width="wide">
      <PageHeader
        eyebrow="Administración"
        title="Auditoría"
        description="Registro inalterable de las acciones relevantes: quién, qué, cuándo, desde dónde y con qué resultado."
        actions={
          <Button variant="secondary" onClick={exportCsv} loading={isExporting} icon={<IconDownload className="h-4 w-4" />}>
            Exportar CSV
          </Button>
        }
      />

      <Card>
        <div className="grid gap-2 border-b border-line p-3 sm:grid-cols-2 lg:grid-cols-[1fr_auto_auto_auto_auto_auto]">
          <label className="relative">
            <span className="sr-only">Buscar</span>
            <IconSearch className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-fg-subtle" />
            <input
              value={filters.q ?? ""}
              onChange={(e) => set("q", e.target.value)}
              placeholder="Usuario, acción o recurso…"
              className="field-input h-9 pl-8"
            />
          </label>
          <select aria-label="Módulo" value={filters.module ?? ""} onChange={(e) => set("module", e.target.value)} className="field-input h-9">
            <option value="">Todos los módulos</option>
            {(page?.modules ?? Object.keys(MODULE_LABELS)).map((m) => (
              <option key={m} value={m}>
                {MODULE_LABELS[m] ?? m}
              </option>
            ))}
          </select>
          <select aria-label="Acción" value={filters.action ?? ""} onChange={(e) => set("action", e.target.value)} className="field-input h-9">
            {ACTION_GROUPS.map((a) => (
              <option key={a.value} value={a.value}>
                {a.label}
              </option>
            ))}
          </select>
          <select aria-label="Resultado" value={filters.result ?? ""} onChange={(e) => set("result", e.target.value)} className="field-input h-9">
            <option value="">Todos los resultados</option>
            {Object.entries(RESULT_LABELS).map(([value, r]) => (
              <option key={value} value={value}>
                {r.label}
              </option>
            ))}
          </select>
          <input
            type="date"
            aria-label="Desde"
            value={filters.date_from ?? ""}
            onChange={(e) => set("date_from", e.target.value)}
            className="field-input h-9"
          />
          <input
            type="date"
            aria-label="Hasta"
            value={filters.date_to ?? ""}
            onChange={(e) => set("date_to", e.target.value)}
            className="field-input h-9"
          />
        </div>

        {error && <Alert tone="danger" className="m-3">{error}</Alert>}
        {page === null && !error ? (
          <LoadingBlock label="Cargando registros…" />
        ) : page && page.items.length === 0 ? (
          <EmptyState
            icon={<IconClipboard className="h-5 w-5" />}
            title={hasFilters ? "Ningún registro coincide" : "Aún no hay registros"}
            description={hasFilters ? "Ajusta o limpia los filtros." : "Las acciones de los usuarios aparecerán aquí."}
            action={hasFilters && <Button variant="secondary" size="sm" onClick={() => setFilters({})}>Limpiar filtros</Button>}
          />
        ) : (
          page && (
            <div className="overflow-x-auto">
              <table className="table-base">
                <thead>
                  <tr>
                    <th scope="col" className="w-8">
                      <span className="sr-only">Detalle</span>
                    </th>
                    <th scope="col">Fecha y hora</th>
                    <th scope="col">Usuario</th>
                    <th scope="col">Acción</th>
                    <th scope="col">Módulo</th>
                    <th scope="col">Resultado</th>
                    <th scope="col">Recurso</th>
                  </tr>
                </thead>
                <tbody>
                  {page.items.map((entry) => {
                    const result = RESULT_LABELS[entry.result] ?? { label: entry.result, tone: "neutral" as const };
                    const open = expanded === entry.id;
                    return (
                      <Fragment key={entry.id}>
                        <tr>
                          <td>
                            <button
                              onClick={() => setExpanded(open ? null : entry.id)}
                              aria-expanded={open}
                              aria-label={open ? "Ocultar detalle" : "Ver detalle"}
                              className="rounded p-1 text-fg-subtle hover:bg-surface-3 hover:text-fg"
                            >
                              {open ? <IconChevronDown className="h-3.5 w-3.5" /> : <IconChevronRight className="h-3.5 w-3.5" />}
                            </button>
                          </td>
                          <td className="whitespace-nowrap text-xs text-fg-muted">{formatDateTime(entry.occurred_at)}</td>
                          <td className="max-w-[14rem] truncate">{entry.actor_email ?? <span className="text-fg-subtle">Sistema</span>}</td>
                          <td>
                            <p>{ACTION_LABELS[entry.action] ?? entry.action}</p>
                            <p className="font-mono text-[11px] text-fg-subtle">{entry.action}</p>
                          </td>
                          <td className="whitespace-nowrap text-fg-muted">{MODULE_LABELS[entry.module] ?? entry.module}</td>
                          <td>
                            <Badge tone={result.tone}>{result.label}</Badge>
                          </td>
                          <td className="max-w-[12rem] truncate font-mono text-xs text-fg-muted">{entry.resource_id ?? "—"}</td>
                        </tr>
                        {open && (
                          <tr>
                            <td />
                            <td colSpan={6} className="bg-surface-2/60">
                              <dl className="grid gap-x-6 gap-y-1 text-xs sm:grid-cols-3">
                                <div>
                                  <dt className="text-fg-subtle">Operación</dt>
                                  <dd className="font-mono">{entry.operation_id ?? "—"}</dd>
                                </div>
                                <div>
                                  <dt className="text-fg-subtle">IP</dt>
                                  <dd className="font-mono">{entry.ip ?? "—"}</dd>
                                </div>
                                <div>
                                  <dt className="text-fg-subtle">Tipo de recurso</dt>
                                  <dd>{entry.resource_type ?? "—"}</dd>
                                </div>
                              </dl>
                              <pre className="mt-2 max-h-64 overflow-auto rounded-lg border border-line bg-surface p-3 font-mono text-[11px] text-fg">
                                {JSON.stringify(entry.context, null, 2)}
                              </pre>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )
        )}

        {page && total > 0 && (
          <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-xs text-fg-muted">
            <span>
              {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} de {total}
            </span>
            <div className="flex gap-2">
              <Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}>
                Anterior
              </Button>
              <Button size="sm" variant="secondary" disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset((o) => o + PAGE_SIZE)}>
                Siguiente
              </Button>
            </div>
          </div>
        )}
      </Card>
    </Page>
  );
}
