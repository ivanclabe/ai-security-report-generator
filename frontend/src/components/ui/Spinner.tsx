export function Spinner({ className = "h-4 w-4", label }: { className?: string; label?: string }) {
  return (
    <span
      role={label ? "status" : undefined}
      aria-label={label}
      className={`inline-block animate-spin rounded-full border-2 border-current border-t-transparent opacity-80 ${className}`}
    />
  );
}

export function LoadingBlock({ label = "Cargando…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center justify-center gap-2 py-12 text-sm text-fg-muted">
      <Spinner className="h-4 w-4 text-primary" />
      {label}
    </div>
  );
}

export function Skeleton({ className = "h-4 w-full" }: { className?: string }) {
  return <span aria-hidden="true" className={`block animate-pulse rounded-md bg-surface-3 ${className}`} />;
}
