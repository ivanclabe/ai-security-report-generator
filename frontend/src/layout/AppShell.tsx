import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { IconLogout, IconMenu, IconMoon, IconShield, IconSun, IconX } from "../components/icons";
import { Toaster } from "../components/ui/Toaster";
import { useAuthStore } from "../store/useAuthStore";
import { usePreferencesStore } from "../store/usePreferencesStore";
import { useSourceStatusStore } from "../store/useSourceStatusStore";
import { NAV_GROUPS, SETTINGS_ITEM, findNavItem, type NavItem } from "./navigation";

function NavEntry({ item, onNavigate }: { item: NavItem; onNavigate: () => void }) {
  return (
    <NavLink
      to={item.to}
      end={item.end}
      onClick={onNavigate}
      className={({ isActive }) =>
        `group flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors ${
          isActive ? "bg-nav-active font-medium text-nav-active-fg" : "text-nav-fg hover:bg-nav-hover"
        }`
      }
    >
      {({ isActive }) => (
        <>
          <item.icon
            className={`h-4 w-4 shrink-0 ${isActive ? "text-nav-active-fg" : "text-nav-muted group-hover:text-nav-fg"}`}
            aria-hidden="true"
          />
          <span className="truncate">{item.label}</span>
        </>
      )}
    </NavLink>
  );
}

function Navigation({ onNavigate }: { onNavigate: () => void }) {
  const me = useAuthStore((s) => s.me);
  const signOut = useAuthStore((s) => s.signOut);
  const initials = (me?.display_name || me?.email || "?").slice(0, 1).toUpperCase();

  return (
    <div className="flex h-full w-64 flex-col border-r border-line bg-nav">
      <Link to="/" onClick={onNavigate} className="flex items-center gap-2.5 px-4 py-4">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-500 shadow-sm">
          <IconShield className="h-4 w-4 text-white" aria-hidden="true" />
        </span>
        <span className="min-w-0 leading-tight">
          <span className="block truncate text-sm font-semibold text-nav-fg">Informes de Seguridad</span>
          <span className="block truncate text-xs text-nav-muted">Centro de Operaciones (SOC)</span>
        </span>
      </Link>

      <nav aria-label="Módulos" className="flex-1 space-y-5 overflow-y-auto px-3 pb-4 pt-1">
        {NAV_GROUPS.map((group) => {
          const items = group.items.filter((i) => !i.adminOnly || me?.is_admin);
          if (!items.length) return null;
          return (
            <div key={group.label}>
              <p className="mb-1 px-2.5 text-[11px] font-semibold uppercase tracking-wider text-nav-muted">{group.label}</p>
              <div className="space-y-0.5">
                {items.map((item) => (
                  <NavEntry key={item.to} item={item} onNavigate={onNavigate} />
                ))}
              </div>
            </div>
          );
        })}
      </nav>

      <div className="space-y-1 border-t border-line p-3">
        <NavEntry item={SETTINGS_ITEM} onNavigate={onNavigate} />
        <div className="flex items-center gap-2.5 rounded-lg px-2.5 py-2">
          <span
            aria-hidden="true"
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-surface-3 text-xs font-semibold text-fg"
          >
            {initials}
          </span>
          <span className="min-w-0 flex-1 leading-tight">
            <span className="block truncate text-xs font-medium text-nav-fg">{me?.display_name || me?.email}</span>
            <span className="block text-[11px] text-nav-muted">{me?.is_admin ? "Administrador" : "Operador"}</span>
          </span>
          <button
            onClick={() => signOut("user")}
            aria-label="Cerrar sesión"
            title="Cerrar sesión"
            className="rounded-md p-1.5 text-nav-muted hover:bg-nav-hover hover:text-nav-fg"
          >
            <IconLogout className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

function SourcePill() {
  const status = useSourceStatusStore((s) => s.status);
  if (!status || !status.provider_active) return null;
  const ok = status.configured;
  return (
    <Link
      to="/fuente-de-datos"
      className={`hidden items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium sm:inline-flex ${
        ok ? "bg-success-subtle text-success-fg" : "bg-warning-subtle text-warning-fg"
      }`}
      title={ok ? `Fuente de datos: ${status.host}` : "La fuente de datos no está configurada"}
    >
      <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-current" />
      {ok ? `Fuente: ${status.host}` : "Fuente sin configurar"}
    </Link>
  );
}

function ThemeToggle() {
  const theme = usePreferencesStore((s) => s.theme);
  const setTheme = usePreferencesStore((s) => s.setTheme);
  const isDark = document.documentElement.classList.contains("dark");
  return (
    <button
      onClick={() => setTheme(isDark ? "light" : "dark")}
      aria-label={isDark ? "Cambiar a modo claro" : "Cambiar a modo oscuro"}
      title={`Tema: ${theme === "system" ? "según el sistema" : theme === "dark" ? "oscuro" : "claro"}`}
      className="rounded-lg p-2 text-fg-muted hover:bg-surface-2 hover:text-fg"
    >
      {isDark ? <IconSun className="h-4 w-4" /> : <IconMoon className="h-4 w-4" />}
    </button>
  );
}

export function AppShell() {
  const [isNavOpen, setIsNavOpen] = useState(false);
  const location = useLocation();
  const current = findNavItem(location.pathname);
  const loadStatus = useSourceStatusStore((s) => s.load);
  // re-render the header icon when the theme flips
  usePreferencesStore((s) => s.theme);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  useEffect(() => {
    document.title = current ? `${current.label} · Informes de Seguridad` : "Informes de Seguridad";
  }, [current]);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-canvas">
      <a
        href="#contenido"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[70] focus:rounded-md focus:bg-surface focus:px-3 focus:py-2 focus:text-sm focus:shadow-pop"
      >
        Saltar al contenido
      </a>

      {isNavOpen && (
        <div className="fixed inset-0 z-30 bg-black/40 lg:hidden" onClick={() => setIsNavOpen(false)} aria-hidden="true" />
      )}
      <div
        className={`fixed inset-y-0 left-0 z-40 transition-transform lg:static lg:translate-x-0 ${
          isNavOpen ? "translate-x-0 shadow-pop" : "-translate-x-full"
        }`}
      >
        <Navigation onNavigate={() => setIsNavOpen(false)} />
        {isNavOpen && (
          <button
            onClick={() => setIsNavOpen(false)}
            aria-label="Cerrar menú"
            className="absolute right-[-44px] top-3 rounded-md bg-surface p-2 text-fg shadow-pop lg:hidden"
          >
            <IconX className="h-4 w-4" />
          </button>
        )}
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-line bg-surface/80 px-4 backdrop-blur sm:px-6">
          <div className="flex min-w-0 items-center gap-2">
            <button
              onClick={() => setIsNavOpen(true)}
              aria-label="Abrir menú"
              className="-ml-1 rounded-md p-1.5 text-fg-muted hover:bg-surface-2 lg:hidden"
            >
              <IconMenu className="h-5 w-5" />
            </button>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-fg">{current?.label ?? "Informes de Seguridad"}</p>
              {current && <p className="hidden truncate text-xs text-fg-subtle sm:block">{current.description}</p>}
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            <SourcePill />
            <ThemeToggle />
          </div>
        </header>
        <main id="contenido" className="flex-1 overflow-y-auto" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
      <Toaster />
    </div>
  );
}
