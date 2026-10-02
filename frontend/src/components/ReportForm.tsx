import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AUDIENCES } from "../lib/constants";
import * as api from "../services/api";
import { useConversationStore } from "../store/useConversationStore";
import { usePreferencesStore } from "../store/usePreferencesStore";
import { useSourceStatusStore } from "../store/useSourceStatusStore";
import type { Company, ErrorCode, ReportInfo, ReportTemplate } from "../types";
import { IconArrowRight, IconFilePlus } from "./icons";
import { ProgressStatus } from "./ProgressStatus";
import { ReportCard } from "./ReportCard";
import { SourceNotConfiguredNotice } from "./SourceNotConfiguredNotice";
import { Alert } from "./ui/Alert";
import { Button } from "./ui/Button";
import { Card, CardBody, CardHeader } from "./ui/Card";
import { Field } from "./ui/Field";

const RISK_LEVELS = [
  { value: "Critico", label: "Crítico" },
  { value: "Alto", label: "Alto" },
  { value: "Medio", label: "Medio" },
  { value: "Bajo", label: "Bajo" },
];

const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

function presets() {
  const today = new Date();
  const firstThis = new Date(today.getFullYear(), today.getMonth(), 1);
  const lastPrev = new Date(firstThis.getTime() - 86400000);
  const firstPrev = new Date(lastPrev.getFullYear(), lastPrev.getMonth(), 1);
  const weekAgo = new Date(today.getTime() - 6 * 86400000);
  return [
    { label: "Mes anterior", start: iso(firstPrev), end: iso(lastPrev) },
    { label: "Mes actual", start: iso(firstThis), end: iso(today) },
    { label: "Últimos 7 días", start: iso(weekAgo), end: iso(today) },
  ];
}

type Result = { report: ReportInfo | null; message: string; isError: boolean; errorCode?: ErrorCode; conversationId?: string };

export function ReportForm() {
  const navigate = useNavigate();
  const loadConversations = useConversationStore((s) => s.loadConversations);
  const selectConversation = useConversationStore((s) => s.selectConversation);
  const prefs = usePreferencesStore((s) => s.preferences);
  const sourceStatus = useSourceStatusStore((s) => s.status);
  const loadSourceStatus = useSourceStatusStore((s) => s.load);

  const [companies, setCompanies] = useState<Company[]>([]);
  const [templates, setTemplates] = useState<ReportTemplate[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [companyId, setCompanyId] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [reportType, setReportType] = useState("");
  const [audience, setAudience] = useState(prefs.default_audience);
  const [categoriesText, setCategoriesText] = useState("");
  const [riskLevels, setRiskLevels] = useState<string[]>([]);
  const [format, setFormat] = useState<string>(prefs.default_format);
  const selectedCompany = companies.find((c) => c.id === companyId);
  const periodPresets = useMemo(() => presets(), []);
  const dateError =
    startDate && endDate && startDate > endDate ? "La fecha inicial debe ser anterior o igual a la fecha final." : null;

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [progressMessage, setProgressMessage] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);

  const sourceBlocked = sourceStatus?.provider_active && !sourceStatus.configured;

  useEffect(() => {
    loadSourceStatus();
    api
      .listCompanies()
      .then(setCompanies)
      .catch((err) => setLoadError(err instanceof Error ? err.message : "No se pudieron cargar las empresas."));
    api
      .listReportTemplates()
      .then((list) => {
        setTemplates(list);
        // keep the visible <select> choice and the state in sync from the start
        setReportType((current) => current || list[0]?.key || "");
      })
      .catch(() => setTemplates([]));
  }, [loadSourceStatus]);

  function toggleRiskLevel(level: string) {
    setRiskLevels((prev) => (prev.includes(level) ? prev.filter((l) => l !== level) : [...prev, level]));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const company = selectedCompany;
    if (!company || !startDate || !endDate || dateError) return;

    setIsSubmitting(true);
    setResult(null);
    setProgressMessage("Validando parámetros…");

    const categories = categoriesText
      .split(",")
      .map((c) => c.trim())
      .filter(Boolean);

    try {
      await api.generateReport(
        {
          company: company.name,
          start_date: startDate,
          end_date: endDate,
          report_type: reportType || undefined,
          audience: audience || undefined,
          focus_categories: categories.length ? categories : undefined,
          risk_level_filter: riskLevels.length ? riskLevels : undefined,
          format,
        },
        (event) => {
          if (event.event === "progress") {
            setProgressMessage(event.message);
          } else if (event.event === "result") {
            setResult({
              report: event.report,
              message: event.message,
              isError: event.status === "error",
              errorCode: event.error_code ?? null,
              conversationId: event.conversation_id,
            });
            if (event.error_code === "source_not_configured") loadSourceStatus();
            loadConversations().catch(() => {});
          }
        },
      );
    } catch (err) {
      setResult({ report: null, message: err instanceof Error ? err.message : "Algo salió mal.", isError: true });
    } finally {
      setIsSubmitting(false);
      setProgressMessage(null);
    }
  }

  const canSubmit = !isSubmitting && !!companyId && !!startDate && !!endDate && !dateError && !sourceBlocked;

  return (
    <div className="space-y-5">
      {sourceBlocked && <SourceNotConfiguredNotice missing={sourceStatus?.missing} />}
      {loadError && <Alert tone="danger">{loadError}</Alert>}

      <form onSubmit={handleSubmit} className="space-y-5">
        <Card>
          <CardHeader title="1. Empresa y período" description="¿De quién y de qué fechas es el informe?" />
          <CardBody className="grid gap-4 sm:grid-cols-2">
            <Field
              label="Empresa"
              hint={selectedCompany?.consecutivo ? `Serie de alarmas: ${selectedCompany.consecutivo}` : undefined}
            >
              {(props) => (
                <select {...props} value={companyId} onChange={(e) => setCompanyId(e.target.value)} required className="field-input">
                  <option value="" disabled>
                    {companies.length ? "Selecciona una empresa" : "Cargando empresas…"}
                  </option>
                  {companies.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <Field label="Formato de salida">
              {(props) => (
                <select {...props} value={format} onChange={(e) => setFormat(e.target.value)} className="field-input">
                  <option value="docx">Word (.docx)</option>
                  <option value="pdf">PDF (.pdf)</option>
                </select>
              )}
            </Field>
            <Field label="Fecha inicial" error={dateError}>
              {(props) => (
                <input {...props} type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} required className="field-input" />
              )}
            </Field>
            <Field label="Fecha final">
              {(props) => (
                <input {...props} type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} required className="field-input" />
              )}
            </Field>
            <div className="flex flex-wrap items-center gap-2 sm:col-span-2">
              <span className="text-xs text-fg-subtle">Atajos:</span>
              {periodPresets.map((p) => (
                <button
                  key={p.label}
                  type="button"
                  onClick={() => {
                    setStartDate(p.start);
                    setEndDate(p.end);
                  }}
                  className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                    startDate === p.start && endDate === p.end
                      ? "border-primary bg-primary-subtle text-primary-subtle-fg"
                      : "border-line text-fg-muted hover:border-line-strong hover:text-fg"
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="2. Tipo de informe" description="Plantilla y nivel de detalle del documento." />
          <CardBody className="grid gap-4 sm:grid-cols-2">
            <Field label="Tipo de informe">
              {(props) => (
                <select {...props} value={reportType} onChange={(e) => setReportType(e.target.value)} className="field-input">
                  {templates.map((t) => (
                    <option key={t.key} value={t.key}>
                      {t.name}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <Field label="Nivel de detalle">
              {(props) => (
                <select {...props} value={audience} onChange={(e) => setAudience(e.target.value)} className="field-input">
                  {AUDIENCES.map((a) => (
                    <option key={a.value} value={a.value}>
                      {a.label}
                    </option>
                  ))}
                </select>
              )}
            </Field>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="3. Filtros" description="Opcionales: sin filtros se incluyen todas las alertas del período." />
          <CardBody className="space-y-4">
            <Field label="Categorías de alertas" optional hint="Separadas por coma. Vacío = todas las categorías.">
              {(props) => (
                <input
                  {...props}
                  type="text"
                  value={categoriesText}
                  onChange={(e) => setCategoriesText(e.target.value)}
                  placeholder="ej. Agente desconectado, Exfiltración por servicio web"
                  className="field-input"
                />
              )}
            </Field>
            <fieldset>
              <legend className="mb-1.5 text-sm font-medium text-fg">Severidad</legend>
              <div className="flex flex-wrap gap-2">
                {RISK_LEVELS.map((level) => {
                  const checked = riskLevels.includes(level.value);
                  return (
                    <label
                      key={level.value}
                      className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-1.5 text-sm transition-colors ${
                        checked ? "border-primary bg-primary-subtle text-primary-subtle-fg" : "border-line text-fg-muted hover:border-line-strong"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleRiskLevel(level.value)}
                        className="h-3.5 w-3.5 accent-[rgb(var(--primary))]"
                      />
                      {level.label}
                    </label>
                  );
                })}
              </div>
              <p className="mt-1.5 text-xs text-fg-subtle">Sin selección = todos los niveles.</p>
            </fieldset>
          </CardBody>
        </Card>

        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={!canSubmit} loading={isSubmitting} icon={<IconFilePlus className="h-4 w-4" aria-hidden="true" />}>
            {isSubmitting ? "Generando informe…" : "Generar informe"}
          </Button>
          {!isSubmitting && !canSubmit && !sourceBlocked && (
            <span className="text-xs text-fg-subtle">Completa la empresa y el período para continuar.</span>
          )}
        </div>
      </form>

      {isSubmitting && progressMessage && (
        <Card className="px-5 py-4">
          <ProgressStatus message={progressMessage} />
          <p className="mt-2 pl-10 text-xs text-fg-subtle">Puedes seguir usando la aplicación; el informe se guarda al terminar.</p>
        </Card>
      )}

      {result && (
        <div className="space-y-3" aria-live="polite">
          {result.errorCode === "source_not_configured" ? (
            <SourceNotConfiguredNotice missing={sourceStatus?.missing} />
          ) : (
            <Alert tone={result.isError ? "danger" : "success"} title={result.isError ? "No se pudo generar el informe" : "Informe listo"}>
              <span className="whitespace-pre-wrap">{result.message}</span>
            </Alert>
          )}
          {result.report && (
            <div className="flex flex-wrap items-end gap-3">
              <ReportCard report={result.report} showQuickActions={false} />
              {result.conversationId && (
                <Button
                  variant="secondary"
                  onClick={async () => {
                    await selectConversation(result.conversationId!);
                    navigate("/asistente");
                  }}
                  icon={<IconArrowRight className="h-4 w-4" aria-hidden="true" />}
                >
                  Ajustarlo con el asistente
                </Button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
