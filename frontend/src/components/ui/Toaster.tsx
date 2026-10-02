import { useToastStore } from "../../store/useToastStore";
import { IconAlertCircle, IconCheckCircle, IconInfo, IconX } from "../icons";

const TONES = {
  success: { cls: "border-success/30", Icon: IconCheckCircle, icon: "text-success" },
  error: { cls: "border-danger/30", Icon: IconAlertCircle, icon: "text-danger" },
  info: { cls: "border-info/30", Icon: IconInfo, icon: "text-info" },
} as const;

export function Toaster() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);
  return (
    <div aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2">
      {toasts.map((t) => {
        const tone = TONES[t.tone];
        return (
          <div
            key={t.id}
            role={t.tone === "error" ? "alert" : "status"}
            className={`pointer-events-auto flex items-start gap-2.5 rounded-lg border bg-surface px-3.5 py-3 text-sm text-fg shadow-pop ${tone.cls}`}
          >
            <tone.Icon className={`mt-0.5 h-4 w-4 shrink-0 ${tone.icon}`} aria-hidden="true" />
            <p className="flex-1">{t.message}</p>
            <button onClick={() => dismiss(t.id)} aria-label="Cerrar aviso" className="rounded p-0.5 text-fg-subtle hover:text-fg">
              <IconX className="h-3.5 w-3.5" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
