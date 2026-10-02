export function ProgressStatus({ message }: { message: string }) {
  return (
    <div role="status" aria-live="polite" className="flex items-center gap-2.5 pl-10 text-sm text-fg-muted">
      <span className="relative flex h-2.5 w-2.5">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-50" />
        <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-primary" />
      </span>
      {message}
    </div>
  );
}
