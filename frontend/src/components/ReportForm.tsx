import { useEffect, useState } from "react";
import * as api from "../services/api";
import { useConversationStore } from "../store/useConversationStore";
import type { Company, ReportInfo, ReportTemplate } from "../types";
import { ProgressStatus } from "./ProgressStatus";
import { ReportCard } from "./ReportCard";

const RISK_LEVELS = ["Critico", "Alto", "Medio", "Bajo"];
const AUDIENCES = [
  { value: "", label: "General" },
  { value: "ejecutivo", label: "Ejecutivo" },
  { value: "tecnico", label: "Técnico" },
];

export function ReportForm() {
  const loadConversations = useConversationStore((s) => s.loadConversations);
  const selectConversation = useConversationStore((s) => s.selectConversation);

  const [companies, setCompanies] = useState<Company[]>([]);
  const [templates, setTemplates] = useState<ReportTemplate[]>([]);

  const [companyId, setCompanyId] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [reportType, setReportType] = useState("");
  const [audience, setAudience] = useState("");
  const [categoriesText, setCategoriesText] = useState("");
  const [riskLevels, setRiskLevels] = useState<string[]>([]);
  const [format, setFormat] = useState("docx");

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [progressMessage, setProgressMessage] = useState<string | null>(null);
  const [result, setResult] = useState<{ report: ReportInfo | null; message: string; isError: boolean } | null>(
    null,
  );

  useEffect(() => {
    api.listCompanies().then(setCompanies).catch(() => setCompanies([]));
    api.listReportTemplates().then(setTemplates).catch(() => setTemplates([]));
  }, []);

  function toggleRiskLevel(level: string) {
    setRiskLevels((prev) => (prev.includes(level) ? prev.filter((l) => l !== level) : [...prev, level]));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const company = companies.find((c) => c.id === companyId);
    if (!company || !startDate || !endDate) return;

    setIsSubmitting(true);
    setResult(null);
    setProgressMessage("Validando parámetros...");

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
            setResult({ report: event.report, message: event.message, isError: event.status === "error" });
            loadConversations();
            if (event.conversation_id) selectConversation(event.conversation_id);
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

  return (
    <div className="mx-auto max-w-2xl px-6 py-8">
      <h1 className="text-lg font-semibold text-slate-900">Generar informe (formulario)</h1>
      <p className="mt-1 text-sm text-slate-500">
        Genera un informe con parámetros exactos — misma lógica interna que el chat, resultado reproducible.
      </p>

      <form onSubmit={handleSubmit} className="mt-6 space-y-5">
        <div className="grid grid-cols-2 gap-4">
          <label className="block text-sm font-medium text-slate-700">
            Empresa
            <select
              value={companyId}
              onChange={(e) => setCompanyId(e.target.value)}
              required
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-slate-400"
            >
              <option value="" disabled>
                Selecciona una empresa
              </option>
              {companies.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>

          <label className="block text-sm font-medium text-slate-700">
            Tipo de informe
            <select
              value={reportType}
              onChange={(e) => setReportType(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-slate-400"
            >
              {templates.map((t) => (
                <option key={t.key} value={t.key}>
                  {t.name}
                </option>
              ))}
            </select>
          </label>

          <label className="block text-sm font-medium text-slate-700">
            Fecha inicial
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              required
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-slate-400"
            />
          </label>

          <label className="block text-sm font-medium text-slate-700">
            Fecha final
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              required
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-slate-400"
            />
          </label>

          <label className="block text-sm font-medium text-slate-700">
            Nivel de detalle
            <select
              value={audience}
              onChange={(e) => setAudience(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-slate-400"
            >
              {AUDIENCES.map((a) => (
                <option key={a.value} value={a.value}>
                  {a.label}
                </option>
              ))}
            </select>
          </label>

          <label className="block text-sm font-medium text-slate-700">
            Formato de salida
            <select
              value={format}
              onChange={(e) => setFormat(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-slate-400"
            >
              <option value="docx">Word (.docx)</option>
              <option value="pdf">PDF (.pdf)</option>
            </select>
          </label>
        </div>

        <label className="block text-sm font-medium text-slate-700">
          Categorías de alertas (opcional)
          <input
            type="text"
            value={categoriesText}
            onChange={(e) => setCategoriesText(e.target.value)}
            placeholder="ej. Agente desconectado, Exfiltración por servicio web"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-slate-400"
          />
          <span className="mt-1 block text-xs text-slate-400">
            Separadas por coma. Déjalo vacío para incluir todas las categorías.
          </span>
        </label>

        <div>
          <span className="block text-sm font-medium text-slate-700">Severidad</span>
          <div className="mt-1 flex flex-wrap gap-3">
            {RISK_LEVELS.map((level) => (
              <label key={level} className="flex items-center gap-1.5 text-sm text-slate-600">
                <input
                  type="checkbox"
                  checked={riskLevels.includes(level)}
                  onChange={() => toggleRiskLevel(level)}
                  className="rounded border-slate-300"
                />
                {level}
              </label>
            ))}
          </div>
          <span className="mt-1 block text-xs text-slate-400">Sin selección = todos los niveles.</span>
        </div>

        <button
          type="submit"
          disabled={isSubmitting || !companyId || !startDate || !endDate}
          className="rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isSubmitting ? "Generando..." : "Generar informe"}
        </button>
      </form>

      {isSubmitting && progressMessage && (
        <div className="mt-5">
          <ProgressStatus message={progressMessage} />
        </div>
      )}

      {result && (
        <div className="mt-5">
          <p className={`text-sm ${result.isError ? "text-red-600" : "text-slate-700"}`}>{result.message}</p>
          {result.report && <ReportCard report={result.report} showQuickActions={false} />}
        </div>
      )}
    </div>
  );
}
