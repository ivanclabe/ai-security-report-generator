import { Fragment, useEffect, useState } from "react";
import { IconBeaker, IconPlus, IconTrash } from "../components/icons";
import { SettingsTabs } from "../components/SettingsTabs";
import { Alert } from "../components/ui/Alert";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardBody, CardHeader } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { Page, PageHeader } from "../components/ui/PageHeader";
import { Spinner } from "../components/ui/Spinner";
import { formatDateTime, formatDuration } from "../lib/format";
import * as api from "../services/api";
import { PROVIDER_LABELS, useLLMStore } from "../store/useLLMStore";
import type { Evaluation, EvaluationMetrics, EvaluationResult, LLMProviderKind } from "../types";

const METRICS: { key: keyof EvaluationMetrics; label: string; help: string }[] = [
  { key: "extraction_accuracy", label: "Exactitud de extracción", help: "Empresa, período, formato y filtros entendidos de la petición." },
  { key: "severity_accuracy", label: "Clasificación de severidad", help: "Nivel de riesgo asignado frente a la escala del cliente." },
  { key: "risk_identification", label: "Identificación de riesgos", help: "La narrativa nombra las categorías de alarmas más frecuentes." },
  { key: "recommendation_quality", label: "Calidad de recomendaciones", help: "Sustentadas en alarmas reales y con contenido concreto." },
  { key: "report_quality", label: "Calidad del informe", help: "Pasa la validación y la narrativa está completa." },
  { key: "consistency", label: "Consistencia", help: "Mismo resultado al repetir el mismo caso." },
];

const pct = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v * 100)} %`);

type Row = { provider: LLMProviderKind; model: string };

function ResultsTable({ evaluation }: { evaluation: Evaluation }) {
  const results = evaluation.results;
  if (!results.length) return null;
  const done = results.filter((r): r is EvaluationResult & { metrics: EvaluationMetrics } => r.status === "completed" && !!r.metrics);
  const best = (key: keyof EvaluationMetrics) => Math.max(...done.map((r) => r.metrics[key] ?? -1));
  const bestOverall = Math.max(...done.map((r) => r.overall ?? -1));
  const cell = (value: number | null | undefined, isBest: boolean) => (
    <td className={`text-right tabular-nums ${isBest && done.length > 1 ? "font-semibold text-success" : ""}`}>{pct(value)}</td>
  );

  return (
    <div className="overflow-x-auto">
      <table className="table-base">
        <thead>
          <tr>
            <th scope="col">Métrica</th>
            {results.map((r, i) => (
              <th scope="col" key={i} className="text-right">
                <span className="block normal-case tracking-normal text-fg">{PROVIDER_LABELS[r.provider]}</span>
                <span className="block max-w-[12rem] truncate font-mono text-[11px] normal-case tracking-normal" title={r.model ?? r.requested_model ?? ""}>
                  {r.model ?? r.requested_model ?? "predeterminado"}
                </span>
                {i === 0 && <span className="block text-[10px] normal-case">línea base</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            <td className="font-semibold">Puntaje general</td>
            {results.map((r, i) =>
              r.status === "completed" ? (
                <td key={i} className={`text-right text-base tabular-nums ${r.overall === bestOverall && done.length > 1 ? "font-bold text-success" : "font-semibold"}`}>
                  {pct(r.overall)}
                </td>
              ) : (
                <td key={i} className="text-right">
                  <Badge tone="danger">No disponible</Badge>
                </td>
              ),
            )}
          </tr>
          {METRICS.map((m) => (
            <tr key={m.key}>
              <td>
                <span className="block">{m.label}</span>
                <span className="block text-xs text-fg-subtle">{m.help}</span>
              </td>
              {results.map((r, i) => (r.metrics ? <Fragment key={i}>{cell(r.metrics[m.key], r.metrics[m.key] === best(m.key))}</Fragment> : <td key={i} />))}
            </tr>
          ))}
          <tr>
            <td>Latencia media por llamada</td>
            {results.map((r, i) => (
              <td key={i} className="text-right tabular-nums">{formatDuration(r.avg_latency_ms)}</td>
            ))}
          </tr>
          <tr>
            <td>Llamadas · fallidas</td>
            {results.map((r, i) => (
              <td key={i} className="text-right tabular-nums">{r.calls != null ? `${r.calls} · ${r.failed_calls ?? 0}` : "—"}</td>
            ))}
          </tr>
          <tr>
            <td>Tokens (entrada / salida)</td>
            {results.map((r, i) => (
              <td key={i} className="text-right tabular-nums">
                {r.input_tokens != null ? `${r.input_tokens.toLocaleString("es-CO")} / ${(r.output_tokens ?? 0).toLocaleString("es-CO")}` : "—"}
              </td>
            ))}
          </tr>
          <tr>
            <td>Errores</td>
            {results.map((r, i) => (
              <td key={i} className="text-right" title={(r.errors ?? []).join("\n") || r.error || ""}>
                {r.status === "unavailable" ? <span className="text-xs text-danger">{r.error}</span> : r.error_count ?? 0}
              </td>
            ))}
          </tr>
          <tr>
            <td>Duración total</td>
            {results.map((r, i) => (
              <td key={i} className="text-right tabular-nums">{formatDuration(r.duration_ms)}</td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}

export function AIEvaluationPage() {
  const catalog = useLLMStore((s) => s.catalog);
  const loadCatalog = useLLMStore((s) => s.load);
  const [rows, setRows] = useState<Row[]>([]);
  const [repetitions, setRepetitions] = useState(2);
  const [history, setHistory] = useState<Evaluation[] | null>(null);
  const [current, setCurrent] = useState<Evaluation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    if (!catalog) loadCatalog();
  }, [catalog, loadCatalog]);

  useEffect(() => {
    if (catalog && rows.length === 0) {
      const usable = catalog.providers.filter((p) => p.enabled && p.configured);
      // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time default from the loaded catalog
      setRows(usable.slice(0, 2).map((p) => ({ provider: p.provider, model: p.default_model })));
    }
  }, [catalog, rows.length]);

  useEffect(() => {
    let cancelled = false;
    api
      .listEvaluations()
      .then((list) => {
        if (cancelled) return;
        setHistory(list);
        setCurrent((c) => c ?? list[0] ?? null);
      })
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : "No se pudo cargar el historial."));
    return () => {
      cancelled = true;
    };
  }, []);

  const running = current && (current.status === "queued" || current.status === "running");
  useEffect(() => {
    if (!running || !current) return;
    const timer = window.setInterval(async () => {
      try {
        const updated = await api.getEvaluation(current.id);
        setCurrent(updated);
        if (updated.status === "completed" || updated.status === "failed") {
          setHistory((h) => (h ? h.map((e) => (e.id === updated.id ? updated : e)) : h));
        }
      } catch {
        // keep polling; a transient error must not stop the view
      }
    }, 3000);
    return () => window.clearInterval(timer);
  }, [running, current]);

  async function start() {
    setStarting(true);
    setError(null);
    try {
      const evaluation = await api.startEvaluation(rows.map((r) => ({ provider: r.provider, model: r.model || null })), repetitions);
      setCurrent(evaluation);
      setHistory((h) => [evaluation, ...(h ?? [])]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo iniciar la evaluación.");
    } finally {
      setStarting(false);
    }
  }

  const providers = catalog?.providers ?? [];
  return (
    <Page width="wide">
      <PageHeader title="Configuración" description="Compara proveedores y modelos con los mismos casos para comprobar que cambiar de IA no degrada el informe." />
      <SettingsTabs />
      <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
        <div className="space-y-5">
          <Card>
            <CardHeader title="Nueva evaluación" icon={<IconBeaker className="h-4 w-4" />}
              description="Casos fijos con datos sintéticos: nunca se envían datos de clientes." />
            <CardBody className="space-y-3">
              {rows.map((row, i) => {
                const info = providers.find((p) => p.provider === row.provider);
                return (
                  <div key={i} className="rounded-lg border border-line p-3">
                    <div className="mb-2 flex items-center justify-between text-xs font-semibold text-fg-subtle">
                      {i === 0 ? "Línea base" : `Candidato ${i + 1}`}
                      {rows.length > 1 && (
                        <button onClick={() => setRows(rows.filter((_, j) => j !== i))} aria-label="Quitar candidato" className="rounded p-1 hover:bg-surface-2">
                          <IconTrash className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                    <div className="grid grid-cols-[6.5rem_1fr] gap-2">
                      <select aria-label="Proveedor" value={row.provider} className="field-input h-9 py-0 text-xs"
                        onChange={(e) => {
                          const provider = e.target.value as LLMProviderKind;
                          const next = [...rows];
                          next[i] = { provider, model: providers.find((p) => p.provider === provider)?.default_model ?? "" };
                          setRows(next);
                        }}>
                        {providers.map((p) => (
                          <option key={p.provider} value={p.provider} disabled={!p.enabled || !p.configured}>
                            {p.label}
                          </option>
                        ))}
                      </select>
                      <select aria-label="Modelo" value={row.model} className="field-input h-9 py-0 font-mono text-xs"
                        onChange={(e) => {
                          const next = [...rows];
                          next[i] = { ...row, model: e.target.value };
                          setRows(next);
                        }}>
                        {(info?.models ?? []).map((m) => (
                          <option key={m} value={m}>
                            {m}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                );
              })}
              {rows.length < 4 && (
                <Button variant="secondary" size="sm" icon={<IconPlus className="h-3.5 w-3.5" />}
                  onClick={() => setRows([...rows, { provider: providers[0]?.provider ?? "cloud", model: providers[0]?.default_model ?? "" }])}>
                  Agregar candidato
                </Button>
              )}
              <label className="flex items-center justify-between gap-2 text-sm text-fg">
                Repeticiones (para medir consistencia)
                <select value={repetitions} onChange={(e) => setRepetitions(Number(e.target.value))} className="field-input h-9 w-20">
                  {[1, 2, 3].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
              <p className="text-xs text-fg-subtle">Cada candidato hace unas {6 + 12 + repetitions} llamadas al modelo; puede tardar varios minutos.</p>
              {error && <Alert tone="danger">{error}</Alert>}
              <Button className="w-full" onClick={start} loading={starting} disabled={!rows.length || !!running}>
                {running ? "Evaluación en curso…" : "Iniciar evaluación"}
              </Button>
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Historial" />
            {history === null ? (
              <div className="p-5">
                <Spinner />
              </div>
            ) : history.length === 0 ? (
              <p className="px-5 py-4 text-sm text-fg-subtle">Aún no hay evaluaciones.</p>
            ) : (
              <ul className="divide-y divide-line">
                {history.map((e) => (
                  <li key={e.id}>
                    <button onClick={() => setCurrent(e)}
                      className={`flex w-full items-center justify-between gap-2 px-5 py-2.5 text-left text-xs hover:bg-surface-2 ${current?.id === e.id ? "bg-primary-subtle/50" : ""}`}>
                      <span>
                        <span className="block font-medium text-fg">{e.candidates.map((c) => PROVIDER_LABELS[c.provider]).join(" vs ")}</span>
                        <span className="text-fg-subtle">{formatDateTime(e.created_at)}</span>
                      </span>
                      <Badge tone={e.status === "completed" ? "success" : e.status === "failed" ? "danger" : "info"}>
                        {e.status === "completed" ? "Lista" : e.status === "failed" ? "Falló" : "En curso"}
                      </Badge>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        <Card>
          <CardHeader
            title="Resultados"
            description={current ? `Iniciada ${formatDateTime(current.created_at)} · ${current.repetitions} repeticiones` : undefined}
            actions={running ? <span className="flex items-center gap-1.5 text-xs text-fg-muted"><Spinner className="h-3 w-3" /> {current?.results.length}/{current?.candidates.length} candidatos</span> : undefined}
          />
          {!current ? (
            <EmptyState icon={<IconBeaker className="h-5 w-5" />} title="Sin resultados todavía" description="Elige los candidatos e inicia una evaluación." />
          ) : (
            <div className="space-y-4 p-4">
              {current.status === "failed" && <Alert tone="danger">La evaluación falló: {current.error}</Alert>}
              {current.summary?.degradations.map((d) =>
                d.degraded ? (
                  <Alert key={`${d.provider}-${d.model}`} tone="warning" title={`${PROVIDER_LABELS[d.provider] ?? d.provider} · ${d.model} rinde peor que la línea base`}>
                    Diferencia general {pct(d.overall_delta)}. Métricas afectadas: {Object.keys(d.worse_metrics).map((k) => METRICS.find((m) => m.key === k)?.label ?? k).join(", ") || "—"}.
                  </Alert>
                ) : (
                  <Alert key={`${d.provider}-${d.model}`} tone="success">
                    {PROVIDER_LABELS[d.provider] ?? d.provider} · {d.model} no degrada la calidad frente a la línea base (diferencia {pct(d.overall_delta)}).
                  </Alert>
                ),
              )}
              {running && !current.results.length ? (
                <div className="flex items-center gap-2 py-8 text-sm text-fg-muted" role="status">
                  <Spinner className="h-4 w-4 text-primary" /> Evaluando el primer candidato…
                </div>
              ) : (
                <ResultsTable evaluation={current} />
              )}
            </div>
          )}
        </Card>
      </div>
    </Page>
  );
}
