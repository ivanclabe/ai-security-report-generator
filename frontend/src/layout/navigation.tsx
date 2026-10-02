import type { ComponentType, SVGProps } from "react";
import {
  IconActivity,
  IconBook,
  IconClipboard,
  IconFilePlus,
  IconFolder,
  IconHelp,
  IconHome,
  IconMessage,
  IconServer,
  IconSettings,
} from "../components/icons";

export interface NavItem {
  to: string;
  label: string;
  description: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  adminOnly?: boolean;
  end?: boolean;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Trabajo",
    items: [
      { to: "/", label: "Inicio", description: "Resumen y accesos rápidos", icon: IconHome, end: true },
      { to: "/informes/nuevo", label: "Generar informe", description: "Formulario paso a paso", icon: IconFilePlus },
      { to: "/informes", label: "Informes", description: "Historial y descargas", icon: IconFolder, end: true },
      { to: "/asistente", label: "Asistente", description: "Chat de análisis", icon: IconMessage },
    ],
  },
  {
    label: "Administración",
    items: [
      { to: "/fuente-de-datos", label: "Fuente de datos", description: "Conexión con Alertas y Notificaciones", icon: IconServer },
      { to: "/observabilidad", label: "Observabilidad", description: "Salud y eventos del sistema", icon: IconActivity, adminOnly: true },
      { to: "/auditoria", label: "Auditoría", description: "Quién hizo qué y cuándo", icon: IconClipboard, adminOnly: true },
    ],
  },
  {
    label: "Ayuda",
    items: [
      { to: "/faq", label: "Preguntas frecuentes", description: "Respuestas rápidas", icon: IconHelp },
      { to: "/documentacion", label: "Documentación", description: "Cómo funciona la plataforma", icon: IconBook },
    ],
  },
];

export const SETTINGS_ITEM: NavItem = {
  to: "/configuracion",
  label: "Configuración",
  description: "Apariencia y preferencias",
  icon: IconSettings,
};

export function findNavItem(pathname: string): NavItem | undefined {
  const all = [...NAV_GROUPS.flatMap((g) => g.items), SETTINGS_ITEM];
  return (
    all.find((i) => i.to === pathname) ??
    all.filter((i) => i.to !== "/" && pathname.startsWith(i.to)).sort((a, b) => b.to.length - a.to.length)[0]
  );
}
