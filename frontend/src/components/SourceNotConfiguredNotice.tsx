import { Link } from "react-router-dom";
import { useAuthStore } from "../store/useAuthStore";
import { Alert } from "./ui/Alert";
import { IconArrowRight } from "./icons";

/** Shown wherever a report could not start because the data source is not configured. */
export function SourceNotConfiguredNotice({ missing, compact = false }: { missing?: string[]; compact?: boolean }) {
  const isAdmin = useAuthStore((s) => s.me?.is_admin);
  return (
    <Alert
      tone="warning"
      title="Primero hay que configurar la fuente de datos"
      action={
        <Link
          to="/fuente-de-datos"
          state={{ from: window.location.pathname }}
          className="inline-flex items-center gap-1 rounded-md bg-warning px-2.5 py-1.5 text-xs font-semibold text-white hover:opacity-90 dark:text-fg-inverse"
        >
          {isAdmin ? "Configurar fuente" : "Ver fuente de datos"}
          <IconArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
        </Link>
      }
    >
      {!compact && (
        <>
          {missing && missing.length > 0 ? `Falta ${missing.join(", ")}. ` : ""}
          {isAdmin
            ? "Complétala en Fuente de Datos y vuelve a intentarlo."
            : "Pide a un administrador que la complete; mientras tanto no se consultan datos."}
        </>
      )}
    </Alert>
  );
}
