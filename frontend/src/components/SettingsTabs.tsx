import { NavLink } from "react-router-dom";
import { useAuthStore } from "../store/useAuthStore";

const TABS = [
  { to: "/configuracion", label: "Preferencias", end: true, admin: false },
  { to: "/configuracion/proveedores-ia", label: "Proveedores de IA", end: false, admin: true },
  { to: "/configuracion/evaluacion-ia", label: "Evaluación de IA", end: false, admin: true },
];

export function SettingsTabs() {
  const isAdmin = useAuthStore((s) => s.me?.is_admin);
  const tabs = TABS.filter((t) => !t.admin || isAdmin);
  if (tabs.length < 2) return null;
  return (
    <nav aria-label="Secciones de configuración" className="mb-6 flex gap-1 overflow-x-auto border-b border-line">
      {tabs.map((t) => (
        <NavLink
          key={t.to}
          to={t.to}
          end={t.end}
          className={({ isActive }) =>
            `-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
              isActive ? "border-primary text-fg" : "border-transparent text-fg-muted hover:text-fg"
            }`
          }
        >
          {t.label}
        </NavLink>
      ))}
    </nav>
  );
}
