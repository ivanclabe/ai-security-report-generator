import { useCallback, useEffect, useState } from "react";
import { IconActivity, IconAlertCircle, IconClock, IconRefresh, IconSearch, IconServer } from "../components/icons";
import { Alert } from "../components/ui/Alert";
import { Badge, type Tone } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardHeader } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { Page, PageHeader } from "../components/ui/PageHeader";
import { LoadingBlock, Skeleton } from "../components/ui/Spinner";
import { Tabs } from "../components/ui/Tabs";
import {
  CATEGORY_LABELS,
  EXECUTION_STATUS,
  formatDateTime,
  formatDuration,
  formatRelative,
  formatUptime,
} from "../lib/format";
import * as api from "../services/api";
import type { AgentExecution, ObservabilitySummary, OpsEvent, RequestRecord } from "../types";

const LEVEL_TONE: Record<string, Tone> = { INFO: "info", WARNING: "warning", ERROR: "danger" };

function Metric({ label, value, hint, tone }: { label: string; value: React.ReactNode; hint?: string; tone?: "danger" | "warning" }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-4 shadow-card">
      <p className="text-xs font-medium text-fg-subtle">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tracking-tight ${tone === "danger" ? "text-danger" : tone === "warning" ? "text-warning" : "text-fg"}`}>
        {value}
      </p>
      {hint && <p className="mt-0.5 text-xs text-fg-subtle">{hint}</p>}
    </div>
  );
}

function EventsTab() {
  const [level, setLevel] = useState("");
  const [category, setCategory] = useState("");
  const [q, setQ] = useState("");
  const [hours, setHours] = useState(24);
  const [items, setItems] = useState<OpsEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setItems(null);
    setError(null);
    try {
      const page = await api.listOpsEvents({ level, category, q, hours, limit: 200 });
      setItems(page.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudieron cargar los eventos.");
      setItems([]);
    }
  }, [level, category, q, hours]);

  useEffect(() => {
    const t = window.setTimeout(load, 250);
    return () => window.clearTimeout(t);
  }, [load]);

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
        <label className="relative min-w-[12rem] flex-1">
          <span className="sr-only">Buscar eventos</span>
          <IconSearch className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-fg-subtle" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar en eventos…" className="field-input h-9 pl-8" />
        </label>
        <select aria-label="Nivel" value={level} onChange={(e) => setLevel(e.target.value)} className="field-input h-9 w-auto">
          <option value="">Todos los niveles</option>
          <option value="INFO">INFO</option>
          <option value="WARNING">WARNING</option>
          <option value="ERROR">ERROR</option>
        </select>
        <select aria-label="Categoría" value={category} onChange={(e) => setCategory(e.target.value)} className="field-input h-9 w-auto">
          <option value="">Todas las categorías</option>
          {Object.entries(CATEGORY_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <select aria-label="Período" value={hours} onChange={(e) => setHours(Number(e.target.value))} className="field-input h-9 w-auto">
          <option value={1}>Última hora</option>
          <option value={24}>Últimas 24 h</option>
          <option value={168}>Últimos 7 días</option>
          <option value={720}>Últimos 30 días</option>
        </select>
      </div>
      {error && <Alert tone="danger" className="m-3">{error}</Alert>}
      {items === null ? (
        <LoadingBlock label="Cargando eventos…" />
      ) : items.length === 0 ? (
        <EmptyState icon={<IconActivity className="h-5 w-5" />} title="Sin eventos" description="No hay eventos con estos filtros." />
      ) : (
        <div className="overflow-x-auto">
          <table className="table-base">
            <thead>
              <tr>
                <th scope="col">Cuándo</th>
                <th scope="col">Nivel</th>
                <th scope="col">Categoría</th>
                <th scope="col">Evento</th>
                <th scope="col" className="text-right">Duración</th>
              </tr>
            </thead>
            <tbody>
              {items.map((e, i) => (
                <tr key={e.id ?? i}>
                  <td className="whitespace-nowrap text-xs text-fg-muted" title={formatDateTime(e.occurred_at)}>
                    {formatRelative(e.occurred_at)}
                  </td>
                  <td>
                    <Badge tone={LEVEL_TONE[e.level] ?? "neutral"}>{e.level}</Badge>
                  </td>
                  <td className="whitespace-nowrap text-fg-muted">{CATEGORY_LABELS[e.category] ?? e.category}</td>
                  <td>
                    <p className="text-sm">{e.message}</p>
                    <p className="mt-0.5 font-mono text-[11px] text-fg-subtle">{e.event}</p>
                  </td>
                  <td className="whitespace-nowrap text-right text-fg-muted">{formatDuration(e.duration_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function RequestsTab() {
  const [items, setItems] = useState<RequestRecord[] | null>(null);
  useEffect(() => {
    api
      .listRequests(200)
      .then((r) => setItems(r.items))
      .catch(() => setItems([]));
  }, []);
  if (items === null) return <LoadingBlock label="Cargando solicitudes…" />;
  if (!items.length) return <EmptyState title="Sin solicitudes registradas" description="Se registran desde el último arranque del servidor." />;
  return (
    <div className="overflow-x-auto">
      <table className="table-base">
        <thead>
          <tr>
            <th scope="col">Cuándo</th>
            <th scope="col">Solicitud</th>
            <th scope="col">Estado</th>
            <th scope="col">Usuario</th>
            <th scope="col" className="text-right">Duración</th>
          </tr>
        </thead>
        <tbody>
          {items.map((r, i) => (
            <tr key={`${r.request_id}-${i}`}>
              <td className="whitespace-nowrap text-xs text-fg-muted" title={formatDateTime(r.occurred_at)}>
                {formatRelative(r.occurred_at)}
              </td>
              <td className="font-mono text-xs">
                <span className="mr-2 font-semibold text-fg-muted">{r.method}</span>
                {r.route}
              </td>
              <td>
                <Badge tone={r.status >= 500 ? "danger" : r.status >= 400 ? "warning" : "success"}>{r.status}</Badge>
              </td>
              <td className="text-xs text-fg-muted">{r.actor_email ?? "—"}</td>
              <td className="whitespace-nowrap text-right text-fg-muted">{formatDuration(r.duration_ms)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ExecutionsTab() {
  const [items, setItems] = useState<AgentExecution[] | null>(null);
  useEffect(() => {
    api
      .listExecutions(100)
      .then((r) => setItems(r.items))
      .catch(() => setItems([]));
  }, []);
  if (items === null) return <LoadingBlock label="Cargando ejecuciones…" />;
  if (!items.length) return <EmptyState title="Sin ejecuciones" description="Aparecerán cuando se genere un informe o se use el asistente." />;
  return (
    <div className="overflow-x-auto">
      <table className="table-base">
        <thead>
          <tr>
            <th scope="col">Inicio</th>
            <th scope="col">Modo</th>
            <th scope="col">Estado</th>
            <th scope="col">Empresa</th>
            <th scope="col" className="text-right">Duración</th>
            <th scope="col" className="text-right">Costo est.</th>
          </tr>
        </thead>
        <tbody>
          {items.map((e) => {
            const status = EXECUTION_STATUS[e.status] ?? { label: e.status, tone: "neutral" as const };
            return (
              <tr key={e.id}>
                <td className="whitespace-nowrap text-xs text-fg-muted">{formatDateTime(e.started_at)}</td>
                <td className="text-fg-muted">{e.mode === "deterministic" ? "Formulario" : "Asistente"}</td>
                <td>
                  <Badge tone={status.tone}>{status.label}</Badge>
                  {e.error_count > 0 && <span className="ml-1.5 text-xs text-danger">{e.error_count} errores</span>}
                </td>
                <td className="text-fg-muted">{e.company_id ?? "—"}</td>
                <td className="whitespace-nowrap text-right text-fg-muted">{formatDuration(e.duration_ms)}</td>
                <td className="whitespace-nowrap text-right text-fg-muted">
                  {e.estimated_cost_usd != null ? `US$ ${Number(e.estimated_cost_usd).toFixed(3)}` : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function ObservabilityPage() {
  const [summary, setSummary] = useState<ObservabilitySummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"events" | "requests" | "executions">("events");
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api
      .getObservabilitySummary()
      .then((s) => !cancelled && setSummary(s))
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : "No se pudo cargar el resumen."));
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  function refresh() {
    setSummary(null);
    setError(null);
    setRefreshKey((k) => k + 1);
  }

  const req = summary?.requests_last_hour;
  const errors24 = summary?.events_24h.by_level.ERROR ?? 0;
  const warnings24 = summary?.events_24h.by_level.WARNING ?? 0;

  return (
    <Page width="wide">
      <PageHeader
        eyebrow="Administración"
        title="Observabilidad"
        description="Qué está pasando en la plataforma: solicitudes, fuente de datos, asistente e informes. Sin datos sensibles."
        actions={
          <Button variant="secondary" onClick={refresh} icon={<IconRefresh className="h-4 w-4" />}>
            Actualizar
          </Button>
        }
      />
      {error && <Alert tone="danger" className="mb-4">{error}</Alert>}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {summary ? (
          <>
            <Metric
              label="Solicitudes (última hora)"
              value={req?.total ?? 0}
              hint={`p95 ${formatDuration(req?.p95_duration_ms)} · media ${formatDuration(req?.avg_duration_ms)}`}
            />
            <Metric
              label="Errores (24 h)"
              value={errors24}
              tone={errors24 ? "danger" : undefined}
              hint={`${warnings24} advertencias · ${req?.server_errors ?? 0} errores 5xx en la última hora`}
            />
            <Metric
              label="Fallos de autenticación (1 h)"
              value={req?.auth_failures ?? 0}
              tone={(req?.auth_failures ?? 0) > 5 ? "warning" : undefined}
              hint="Respuestas 401/403"
            />
            <Metric
              label="Ejecuciones (24 h)"
              value={summary.agent_24h.total}
              hint={`${summary.agent_24h.by_status.error ?? 0} con error · media ${formatDuration(summary.agent_24h.avg_duration_ms)}`}
            />
          </>
        ) : (
          [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24 rounded-xl" />)
        )}
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card>
          <CardHeader title="Fuente de datos" icon={<IconServer className="h-4 w-4" />} />
          <div className="space-y-3 px-5 py-4 text-sm">
            {!summary ? (
              <Skeleton className="h-16" />
            ) : (
              <>
                <div className="flex items-center justify-between">
                  <span className="font-mono text-fg">{summary.source.host ?? "—"}</span>
                  <Badge tone={summary.source.configured ? "success" : "warning"} dot>
                    {summary.source.configured ? "Configurada" : "Sin configurar"}
                  </Badge>
                </div>
                {summary.source.last_event ? (
                  <p className="text-xs text-fg-muted">
                    Último contacto {formatRelative(summary.source.last_event.occurred_at)}: {summary.source.last_event.message}
                  </p>
                ) : (
                  <p className="text-xs text-fg-subtle">Sin contacto en las últimas 24 h.</p>
                )}
                {summary.source.last_error && (
                  <Alert tone="danger">
                    <span className="text-xs">
                      Último error {formatRelative(summary.source.last_error.occurred_at)}: {summary.source.last_error.message}
                    </span>
                  </Alert>
                )}
              </>
            )}
          </div>
        </Card>
        <Card>
          <CardHeader title="Proceso" icon={<IconClock className="h-4 w-4" />} />
          <dl className="space-y-2 px-5 py-4 text-sm">
            {!summary ? (
              <Skeleton className="h-16" />
            ) : (
              <>
                <div className="flex justify-between gap-2">
                  <dt className="text-fg-muted">Activo desde</dt>
                  <dd className="text-fg">{formatUptime(summary.process.uptime_seconds)}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-fg-muted">Versión</dt>
                  <dd className="font-mono text-xs text-fg">{summary.process.version ?? "—"}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-fg-muted">Informes generados (24 h)</dt>
                  <dd className="text-fg">{summary.reports_24h}</dd>
                </div>
              </>
            )}
          </dl>
        </Card>
        <Card>
          <CardHeader title="Eventos por categoría (24 h)" icon={<IconAlertCircle className="h-4 w-4" />} />
          <ul className="space-y-1.5 px-5 py-4 text-sm">
            {!summary ? (
              <Skeleton className="h-16" />
            ) : Object.keys(summary.events_24h.by_category).length === 0 ? (
              <li className="text-xs text-fg-subtle">Sin eventos.</li>
            ) : (
              Object.entries(summary.events_24h.by_category)
                .sort((a, b) => b[1] - a[1])
                .map(([cat, count]) => (
                  <li key={cat} className="flex items-center justify-between">
                    <span className="text-fg-muted">{CATEGORY_LABELS[cat] ?? cat}</span>
                    <span className="font-medium text-fg">{count}</span>
                  </li>
                ))
            )}
          </ul>
        </Card>
      </div>

      <Card className="mt-6">
        <div className="px-3 pt-2">
          <Tabs
            label="Vistas de observabilidad"
            value={tab}
            onChange={setTab}
            items={[
              { value: "events", label: "Eventos" },
              { value: "requests", label: "Solicitudes" },
              { value: "executions", label: "Ejecuciones del agente" },
            ]}
          />
        </div>
        <div key={`${tab}-${refreshKey}`}>
          {tab === "events" && <EventsTab />}
          {tab === "requests" && <RequestsTab />}
          {tab === "executions" && <ExecutionsTab />}
        </div>
      </Card>
    </Page>
  );
}
