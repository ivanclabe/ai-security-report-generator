import type { ReactNode } from "react";
import { IconAlertCircle, IconCheckCircle, IconInfo } from "../icons";

type AlertTone = "info" | "success" | "warning" | "danger";

const TONES: Record<AlertTone, string> = {
  info: "border-info/25 bg-info-subtle text-info-fg",
  success: "border-success/25 bg-success-subtle text-success-fg",
  warning: "border-warning/30 bg-warning-subtle text-warning-fg",
  danger: "border-danger/25 bg-danger-subtle text-danger-fg",
};

export function Alert({
  tone = "info",
  title,
  children,
  action,
  className = "",
}: {
  tone?: AlertTone;
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  const Icon = tone === "success" ? IconCheckCircle : tone === "info" ? IconInfo : IconAlertCircle;
  return (
    <div
      role={tone === "danger" || tone === "warning" ? "alert" : "status"}
      className={`flex flex-wrap items-start gap-3 rounded-lg border px-4 py-3 text-sm ${TONES[tone]} ${className}`}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className={title ? "mt-0.5 opacity-90" : ""}>{children}</div>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}
