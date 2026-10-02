import { IconHelp, IconLock } from "../components/icons";
import { EmptyState } from "../components/ui/EmptyState";
import { LinkButton } from "../components/ui/LinkButton";
import { Page } from "../components/ui/PageHeader";

export function NotFoundPage() {
  return (
    <Page width="narrow">
      <EmptyState
        icon={<IconHelp className="h-5 w-5" />}
        title="Esta página no existe"
        description="Revisa la dirección o vuelve al inicio."
        action={<LinkButton to="/">Ir al inicio</LinkButton>}
      />
    </Page>
  );
}

export function ForbiddenPage() {
  return (
    <Page width="narrow">
      <EmptyState
        icon={<IconLock className="h-5 w-5" />}
        title="Sección solo para administradores"
        description="Si necesitas acceso, pídeselo a un administrador de la plataforma."
        action={<LinkButton to="/">Volver al inicio</LinkButton>}
      />
    </Page>
  );
}
