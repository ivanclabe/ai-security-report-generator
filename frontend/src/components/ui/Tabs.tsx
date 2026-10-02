import type { ReactNode } from "react";

export function Tabs<T extends string>({
  value,
  onChange,
  items,
  label,
}: {
  value: T;
  onChange: (value: T) => void;
  items: { value: T; label: ReactNode; count?: number }[];
  label: string;
}) {
  return (
    <div role="tablist" aria-label={label} className="flex gap-1 overflow-x-auto border-b border-line">
      {items.map((item) => {
        const active = item.value === value;
        return (
          <button
            key={item.value}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(item.value)}
            className={`-mb-px flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
              active ? "border-primary text-fg" : "border-transparent text-fg-muted hover:text-fg"
            }`}
          >
            {item.label}
            {item.count !== undefined && (
              <span className="rounded-full bg-surface-3 px-1.5 text-xs text-fg-muted">{item.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
