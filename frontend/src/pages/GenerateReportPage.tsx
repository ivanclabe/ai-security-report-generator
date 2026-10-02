import { ReportForm } from "../components/ReportForm";
import { Page, PageHeader } from "../components/ui/PageHeader";

export function GenerateReportPage() {
  return (
    <Page width="narrow">
      <PageHeader
        eyebrow="Informes"
        title="Generar informe"
        description="Parámetros exactos y resultado reproducible: la misma lógica del asistente, sin conversación."
      />
      <ReportForm />
    </Page>
  );
}
