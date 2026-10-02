import { useEffect, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { Alert } from "../components/ui/Alert";
import { Page, PageHeader } from "../components/ui/PageHeader";

const SECTIONS: { id: string; title: string; body: ReactNode }[] = [
  {
    id: "que-hace",
    title: "Qué hace la aplicación",
    body: (
      <>
        <p>
          Genera informes de gestión de seguridad para cada empresa cliente a partir de las alarmas registradas por el SOC.
          Descarga las alertas de la fuente oficial, las analiza y entrega un documento Word o PDF con resumen ejecutivo,
          métricas, tendencias, técnicas MITRE ATT&CK y recomendaciones respaldadas por alarmas reales.
        </p>
        <p>Todo queda trazado: quién pidió cada informe, con qué datos y qué versión se descargó.</p>
      </>
    ),
  },
  {
    id: "flujo",
    title: "Flujo general de trabajo",
    body: (
      <ol className="list-decimal space-y-1.5 pl-5">
        <li>
          Un administrador configura la <Link to="/fuente-de-datos">Fuente de datos</Link> (una sola vez, o cuando cambie la IP).
        </li>
        <li>
          Pides un informe desde <Link to="/informes/nuevo">Generar informe</Link> o desde el <Link to="/asistente">Asistente</Link>.
        </li>
        <li>La plataforma descarga las alertas, las normaliza y calcula las métricas.</li>
        <li>Se redacta y valida el informe, y se genera el documento.</li>
        <li>
          Lo descargas, o lo ajustas conversando con el Asistente (cada ajuste crea una versión nueva). El historial está en{" "}
          <Link to="/informes">Informes</Link>.
        </li>
      </ol>
    ),
  },
  {
    id: "fuente",
    title: "Configurar las fuentes de datos",
    body: (
      <>
        <p>En Fuente de datos (solo administradores) se definen:</p>
        <ul className="list-disc space-y-1 pl-5">
          <li><strong>Protocolo e IP/host</strong>: el servidor de la fuente. Cambiar la IP es editar solo este campo.</li>
          <li><strong>Ruta base</strong>: prefijo común, p. ej. <code>/ProyectoSOC/views</code>.</li>
          <li><strong>URL de Alertas</strong>: export detallado de alarmas (CSV), base del informe.</li>
          <li><strong>URL de Notificaciones</strong>: panel de indicadores, usado para conciliar totales.</li>
          <li><strong>Usuario y contraseña</strong>: la contraseña se guarda cifrada y nunca se vuelve a mostrar.</li>
          <li><strong>Opciones avanzadas</strong>: verificación TLS, tiempo de espera, límite de filas y conciliación.</li>
        </ul>
        <p>
          «Probar conexión» inicia sesión y descarga una fila de muestra sin guardar nada. «Guardar» vuelve a probar antes de
          aplicar; si la red no está disponible puedes guardar sin probar. Los cambios aplican de inmediato y quedan auditados.
        </p>
        <Alert tone="warning">
          Si la fuente usa <code>http</code>, las credenciales viajan sin cifrar: úsala solo por la VPN y solicita https.
        </Alert>
      </>
    ),
  },
  {
    id: "informes",
    title: "Generar reportes",
    body: (
      <>
        <p>
          El formulario pide empresa, período (con atajos), formato, tipo de informe y nivel de detalle; los filtros por
          categoría y severidad son opcionales. Si la fuente no está configurada, el botón se desactiva y se indica qué falta.
        </p>
        <p>
          Puedes fijar el formato y el nivel de detalle por defecto en <Link to="/configuracion">Configuración</Link>.
        </p>
      </>
    ),
  },
  {
    id: "asistente",
    title: "Usar el chatbot (Asistente)",
    body: (
      <>
        <p>Escribe lo que necesitas en lenguaje natural. Ejemplos:</p>
        <ul className="list-disc space-y-1 pl-5">
          <li>«Genera el informe de THOMAS TGS TPS de agosto en PDF.»</li>
          <li>«Muéstrame solo las alarmas críticas del período.»</li>
          <li>«Hazlo más ejecutivo» (sobre un informe ya generado).</li>
          <li>«¿Cuáles son las técnicas MITRE más frecuentes?»</li>
        </ul>
        <p>
          Si falta un dato (empresa o fechas), el Asistente pregunta. Enter envía; Shift+Enter agrega una línea. Las
          conversaciones se pueden anclar, renombrar y eliminar.
        </p>
      </>
    ),
  },
  {
    id: "analisis",
    title: "Conceptos básicos",
    body: (
      <dl className="space-y-2.5">
        <div>
          <dt className="font-semibold text-fg">Alarma / alerta</dt>
          <dd>Evento de seguridad registrado por el SOC, con fecha, origen, categoría y severidad.</dd>
        </div>
        <div>
          <dt className="font-semibold text-fg">Nivel de riesgo</dt>
          <dd>Se calcula a partir de la severidad (0–100): Bajo, Medio, Alto y Crítico.</dd>
        </div>
        <div>
          <dt className="font-semibold text-fg">MITRE ATT&CK</dt>
          <dd>Marco que clasifica las técnicas de ataque; cada alarma se asocia a una táctica cuando es posible.</dd>
        </div>
        <div>
          <dt className="font-semibold text-fg">Conciliación</dt>
          <dd>Comparación entre el total de Alertas y el que reporta el panel de Notificaciones para detectar exportaciones incompletas.</dd>
        </div>
        <div>
          <dt className="font-semibold text-fg">Versión</dt>
          <dd>Cada ajuste de un informe genera una versión nueva; siempre se descarga la última.</dd>
        </div>
      </dl>
    ),
  },
  {
    id: "errores",
    title: "Qué hacer ante errores comunes",
    body: (
      <dl className="space-y-2.5">
        <div>
          <dt className="font-semibold text-fg">«Primero hay que configurar la fuente de datos»</dt>
          <dd>Falta dirección, usuario o contraseña. Un administrador debe completarlos en Fuente de datos.</dd>
        </div>
        <div>
          <dt className="font-semibold text-fg">«No se pudo conectar a …»</dt>
          <dd>Verifica la VPN/red y que la IP sea la correcta. Si la infraestructura cambió de dirección, actualiza el host.</dd>
        </div>
        <div>
          <dt className="font-semibold text-fg">«La fuente rechazó el usuario o la contraseña»</dt>
          <dd>La credencial cambió o expiró en la fuente. Escribe la nueva en Fuente de datos y prueba la conexión.</dd>
        </div>
        <div>
          <dt className="font-semibold text-fg">«La fuente no devolvió alarmas…»</dt>
          <dd>Puede que no haya alarmas en ese período, o que el nombre de cliente configurado para la empresa no coincida con la fuente.</dd>
        </div>
        <div>
          <dt className="font-semibold text-fg">«Tu sesión expiró»</dt>
          <dd>Inicia sesión de nuevo; tu trabajo guardado no se pierde.</dd>
        </div>
        <div>
          <dt className="font-semibold text-fg">Otro error</dt>
          <dd>Anota la hora y el mensaje; un administrador puede buscarlo en Observabilidad o Auditoría por fecha y usuario.</dd>
        </div>
      </dl>
    ),
  },
];

export function DocsPage() {
  const location = useLocation();
  useEffect(() => {
    if (location.hash) document.getElementById(location.hash.slice(1))?.scrollIntoView({ block: "start" });
  }, [location.hash]);

  return (
    <Page width="wide">
      <PageHeader eyebrow="Ayuda" title="Documentación" description="Lo esencial para trabajar con la plataforma." />
      <div className="grid gap-8 lg:grid-cols-[14rem_1fr]">
        <nav aria-label="Contenido de la documentación" className="lg:sticky lg:top-4 lg:self-start">
          <ol className="space-y-0.5 text-sm">
            {SECTIONS.map((s, i) => (
              <li key={s.id}>
                <a
                  href={`#${s.id}`}
                  className={`block rounded-md px-3 py-1.5 transition-colors hover:bg-surface-2 hover:text-fg ${
                    location.hash === `#${s.id}` ? "bg-primary-subtle font-medium text-primary-subtle-fg" : "text-fg-muted"
                  }`}
                >
                  <span className="mr-1.5 text-fg-subtle">{i + 1}.</span>
                  {s.title}
                </a>
              </li>
            ))}
          </ol>
        </nav>
        <div className="space-y-6">
          {SECTIONS.map((s, i) => (
            <section
              key={s.id}
              id={s.id}
              className="scroll-mt-4 rounded-xl border border-line bg-surface p-6 shadow-card [&_a]:font-medium [&_a]:text-primary hover:[&_a]:underline [&_code]:rounded [&_code]:bg-surface-3 [&_code]:px-1 [&_code]:font-mono [&_code]:text-xs"
            >
              <h2 className="text-base font-semibold text-fg">
                <span className="mr-2 text-fg-subtle">{i + 1}.</span>
                {s.title}
              </h2>
              <div className="mt-3 space-y-3 text-sm leading-relaxed text-fg-muted">{s.body}</div>
            </section>
          ))}
        </div>
      </div>
    </Page>
  );
}
