import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  IconActivity,
  IconArrowRight,
  IconBook,
  IconFilePlus,
  IconFolder,
  IconMessage,
  IconServer,
} from "../components/icons";
import { RecentReportsTable } from "../components/RecentReportsTable";
import { Badge } from "../components/ui/Badge";
import { Card, CardHeader } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { LinkButton } from "../components/ui/LinkButton";
import { Page } from "../components/ui/PageHeader";
import { Skeleton } from "../components/ui/Spinner";
import { formatDuration } from "../lib/format";
import * as api from "../services/api";
import { useAuthStore } from "../store/useAuthStore";
import { useSourceStatusStore } from "../store/useSourceStatusStore";
import type { ObservabilitySummary, RecentReport } from "../types";

function greeting() {
  const hour = new Date().getHours();
  return hour < 12 ? "Buenos días" : hour < 19 ? "Buenas tardes" : "Buenas noches";
}

function QuickAction({
  to,
  icon: Icon,
  title,
  description,
}: {
  to: string;
  icon: typeof IconFilePlus;
  title: string;
  description: string;
}) {
  return (
    <Link
      to={to}
      className="group flex items-start gap-3 rounded-xl border border-line bg-surface p-4 shadow-card transition-colors hover:border-primary/50"
    >
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary-subtle text-primary-subtle-fg">
        <Icon className="h-5 w-5" aria-hidden="true" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1 text-sm font-semibold text-fg">
          {title}
          <IconArrowRight className="h-3.5 w-3.5 opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
        </span>
        <span className="mt-0.5 block text-xs text-fg-muted">{description}</span>
      </span>
    </Link>
  );
}

function SourceCard() {
  const status = useSourceStatusStore((s) => s.status);
  const isAdmin = useAuthStore((s) => s.me?.is_admin);
  return (
    <Card>
      <CardHeader title="Fuente de datos" icon={<IconServer className="h-4 w-4" />} description="Alertas y Notificaciones" />
      <div className="px-5 py-4">
        {!status ? (
          <Skeleton className="h-10" />
        ) : !status.provider_active ? (
          <p className="text-sm text-fg-muted">La app usa datos de demostración.</p>
        ) : status.configured ? (
          <div className="space-y-2">
            <Badge tone="success" dot>
              Configurada
            </Badge>
            <p className="font-mono text-sm text-fg">{status.host}</p>
            {!status.uses_https && <p className="text-xs text-warning-fg">Conexión sin cifrar (http): úsala solo por VPN.</p>}
          </div>
        ) : (
          <div className="space-y-3">
            <Badge tone="warning" dot>
              Sin configurar
            </Badge>
            <p className="text-sm text-fg-muted">Falta {status.missing.join(", ")}. No se pueden generar informes.</p>
            <LinkButton to="/fuente-de-datos" size="sm" variant={isAdmin ? "primary" : "secondary"}>
              {isAdmin ? "Configurar ahora" : "Ver detalles"}
            </LinkButton>
          </div>
        )}
      </div>
    </Card>
  );
}

function HealthCard() {
  const [summary, setSummary] = useState<ObservabilitySummary | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    api.getObservabilitySummary().then(setSummary).catch(() => setFailed(true));
  }, []);
  const errors = summary?.events_24h.by_level.ERROR ?? 0;
  return (
    <Card>
      <CardHeader
        title="Salud del sistema"
        description="Últimas 24 horas"
        icon={<IconActivity className="h-4 w-4" />}
        actions={
          <Link to="/observabilidad" className="text-xs font-medium text-primary hover:underline">
            Ver detalle
          </Link>
        }
      />
      <div className="grid grid-cols-3 gap-3 px-5 py-4 text-center">
        {failed ? (
          <p className="col-span-3 text-sm text-fg-muted">No disponible.</p>
        ) : !summary ? (
          <>
            <Skeleton className="h-12" />
            <Skeleton className="h-12" />
            <Skeleton className="h-12" />
          </>
        ) : (
          <>
            <div>
              <p className={`text-xl font-semibold ${errors ? "text-danger" : "text-fg"}`}>{errors}</p>
              <p className="text-xs text-fg-subtle">Errores</p>
            </div>
            <div>
              <p className="text-xl font-semibold text-fg">{summary.agent_24h.total}</p>
              <p className="text-xs text-fg-subtle">Ejecuciones</p>
            </div>
            <div>
              <p className="text-xl font-semibold text-fg">{formatDuration(summary.agent_24h.avg_duration_ms)}</p>
              <p className="text-xs text-fg-subtle">Duración media</p>
            </div>
          </>
        )}
      </div>
    </Card>
  );
}

export function HomePage() {
  const me = useAuthStore((s) => s.me);
  const [reports, setReports] = useState<RecentReport[] | null>(null);

  useEffect(() => {
    api
      .listRecentReports(5)
      .then(setReports)
      .catch(() => setReports([]));
  }, []);

  const name = me?.display_name?.split(" ")[0] || me?.email?.split("@")[0] || "";

  return (
    <Page width="wide">
      <div className="mb-6">
        <h1 className="text-xl font-semibold tracking-tight text-fg sm:text-2xl">
          {greeting()}
          {name ? `, ${name}` : ""}
        </h1>
        <p className="mt-1 text-sm text-fg-muted">¿Qué necesitas hoy?</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <QuickAction to="/informes/nuevo" icon={IconFilePlus} title="Generar informe" description="Formulario con parámetros exactos" />
        <QuickAction to="/asistente" icon={IconMessage} title="Abrir el asistente" description="Pide o ajusta informes conversando" />
        <QuickAction to="/informes" icon={IconFolder} title="Ver informes" description="Historial y descargas" />
        <QuickAction to="/documentacion" icon={IconBook} title="Cómo funciona" description="Guía rápida de la plataforma" />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader
            title="Informes recientes"
            icon={<IconFolder className="h-4 w-4" />}
            actions={
              <Link to="/informes" className="text-xs font-medium text-primary hover:underline">
                Ver todos
              </Link>
            }
          />
          {reports === null ? (
            <div className="space-y-3 p-5">
              <Skeleton className="h-8" />
              <Skeleton className="h-8" />
              <Skeleton className="h-8" />
            </div>
          ) : reports.length === 0 ? (
            <EmptyState
              icon={<IconFilePlus className="h-5 w-5" />}
              title="Aún no hay informes"
              description="Cuando generes uno aparecerá aquí, listo para descargar."
              action={
                <LinkButton to="/informes/nuevo" size="sm">
                  Generar el primero
                </LinkButton>
              }
            />
          ) : (
            <RecentReportsTable reports={reports} compact />
          )}
        </Card>
        <div className="space-y-6">
          <SourceCard />
          {me?.is_admin && <HealthCard />}
        </div>
      </div>
    </Page>
  );
}
