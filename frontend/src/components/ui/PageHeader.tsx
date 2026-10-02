import type { ReactNode } from "react";

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  eyebrow?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-primary">{eyebrow}</p>}
        <h1 className="text-xl font-semibold tracking-tight text-fg sm:text-2xl">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-fg-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Page({ children, width = "default" }: { children: ReactNode; width?: "default" | "narrow" | "wide" }) {
  const max = width === "narrow" ? "max-w-3xl" : width === "wide" ? "max-w-7xl" : "max-w-5xl";
  return <div className={`mx-auto w-full ${max} px-4 py-6 sm:px-6 lg:px-8 lg:py-8`}>{children}</div>;
}
