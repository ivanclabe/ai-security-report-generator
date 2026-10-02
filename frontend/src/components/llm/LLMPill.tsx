import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useAuthStore } from "../../store/useAuthStore";
import { describeSelection, useLLMStore } from "../../store/useLLMStore";
import { IconChevronDown, IconCpu } from "../icons";
import { LLMSelector } from "./LLMSelector";

/** Always-visible "which AI am I using?" + quick change, without leaving the page. */
export function LLMPill() {
  const catalog = useLLMStore((s) => s.catalog);
  const selection = useLLMStore((s) => s.selection);
  const load = useLLMStore((s) => s.load);
  const isAdmin = useAuthStore((s) => s.me?.is_admin);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!catalog) load();
  }, [catalog, load]);

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const label = describeSelection(selection, catalog);
  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="dialog"
        title={`Modelo de IA: ${label}`}
        className="inline-flex max-w-[16rem] items-center gap-1.5 rounded-full border border-line bg-surface px-2.5 py-1 text-xs font-medium text-fg hover:border-line-strong"
      >
        <IconCpu className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden="true" />
        <span className="hidden truncate sm:inline">{label}</span>
        <span className="sm:hidden">IA</span>
        <IconChevronDown className="h-3 w-3 shrink-0 text-fg-subtle" aria-hidden="true" />
      </button>
      {open && (
        <div
          role="dialog"
          aria-label="Modelo de IA"
          className="absolute right-0 top-full z-50 mt-2 w-[min(26rem,calc(100vw-2rem))] rounded-xl border border-line bg-surface p-4 shadow-pop"
        >
          <p className="mb-3 text-sm font-semibold text-fg">Modelo de IA</p>
          <LLMSelector />
          <p className="mt-3 border-t border-line pt-3 text-xs text-fg-subtle">
            Se usa en tus próximos informes y conversaciones, y queda como tu predeterminado.
            {isAdmin && (
              <>
                {" "}
                <Link to="/configuracion/proveedores-ia" onClick={() => setOpen(false)} className="font-medium text-primary hover:underline">
                  Configurar proveedores
                </Link>
              </>
            )}
          </p>
        </div>
      )}
    </div>
  );
}
