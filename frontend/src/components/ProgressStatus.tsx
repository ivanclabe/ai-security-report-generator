export function ProgressStatus({ message }: { message: string }) {
  return (
    <div role="status" className="flex items-center gap-2 pl-9 text-sm text-slate-500">
      <span className="flex h-2 w-2 animate-pulse rounded-full bg-brand-500" />
      {message}
    </div>
  );
}
