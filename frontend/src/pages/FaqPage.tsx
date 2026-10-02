import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { FAQ } from "../content/faq";
import { IconArrowRight, IconChevronDown, IconHelp, IconSearch } from "../components/icons";
import { EmptyState } from "../components/ui/EmptyState";
import { Page, PageHeader } from "../components/ui/PageHeader";

const normalize = (text: string) =>
  text
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "");

export function FaqPage() {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string>("");

  const results = useMemo(() => {
    const words = normalize(query).split(/\s+/).filter(Boolean);
    return FAQ.filter((c) => !category || c.id === category)
      .map((c) => ({
        ...c,
        items: c.items.filter((item) => {
          const haystack = normalize(`${item.q} ${item.a}`);
          return words.every((w) => haystack.includes(w));
        }),
      }))
      .filter((c) => c.items.length);
  }, [query, category]);
  const count = results.reduce((n, c) => n + c.items.length, 0);

  return (
    <Page width="narrow">
      <PageHeader eyebrow="Ayuda" title="Preguntas frecuentes" description="Respuestas rápidas sobre el uso de la plataforma." />

      <div className="sticky top-0 z-10 -mx-1 mb-5 space-y-3 bg-canvas/95 px-1 pb-3 pt-1 backdrop-blur">
        <label className="relative block">
          <span className="sr-only">Buscar en las preguntas frecuentes</span>
          <IconSearch className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-subtle" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Busca, por ejemplo: «cambiar IP», «PDF», «contraseña»…"
            className="field-input h-11 pl-10 text-base"
            autoFocus
          />
        </label>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Categorías">
          {[{ id: "", title: "Todas" }, ...FAQ].map((c) => (
            <button
              key={c.id}
              onClick={() => setCategory(c.id)}
              aria-pressed={category === c.id}
              className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                category === c.id ? "border-primary bg-primary-subtle text-primary-subtle-fg" : "border-line bg-surface text-fg-muted hover:text-fg"
              }`}
            >
              {c.title}
            </button>
          ))}
        </div>
        <p className="text-xs text-fg-subtle" aria-live="polite">
          {count} {count === 1 ? "respuesta" : "respuestas"}
        </p>
      </div>

      {results.length === 0 ? (
        <EmptyState
          icon={<IconHelp className="h-5 w-5" />}
          title="No encontramos esa pregunta"
          description="Prueba con otras palabras o revisa la documentación."
          action={
            <Link to="/documentacion" className="text-sm font-medium text-primary hover:underline">
              Ir a la documentación
            </Link>
          }
        />
      ) : (
        <div className="space-y-8">
          {results.map((c) => (
            <section key={c.id} aria-labelledby={`faq-${c.id}`}>
              <h2 id={`faq-${c.id}`} className="mb-3 text-xs font-semibold uppercase tracking-wider text-fg-subtle">
                {c.title}
              </h2>
              <div className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface shadow-card">
                {c.items.map((item) => (
                  <details key={item.q} className="group" open={!!query.trim()}>
                    <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4 text-sm font-medium text-fg hover:bg-surface-2 [&::-webkit-details-marker]:hidden">
                      {item.q}
                      <IconChevronDown className="h-4 w-4 shrink-0 text-fg-subtle transition-transform group-open:rotate-180" aria-hidden="true" />
                    </summary>
                    <div className="px-5 pb-4 text-sm leading-relaxed text-fg-muted">
                      <p>{item.a}</p>
                      {item.link && (
                        <Link to={item.link.to} className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline">
                          {item.link.label}
                          <IconArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
                        </Link>
                      )}
                    </div>
                  </details>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </Page>
  );
}
