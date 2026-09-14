export function ProgressStatus({ message }: { message: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-slate-500">
      <span className="flex h-2 w-2 animate-pulse rounded-full bg-slate-400" />
      {message}
    </div>
  );
}
