type BadgeTone = "success" | "danger" | "info" | "warning" | "neutral";

const STATUS_TONE: Record<string, BadgeTone> = {
  online: "success",
  success: "success",
  installed: "success",
  running: "info",
  offline: "danger",
  failed: "danger",
  removed: "danger",
  queued: "neutral",
  unknown: "neutral",
  disabled: "neutral",
};

const TONE_STYLES: Record<BadgeTone, string> = {
  success: "bg-emerald-500/10 text-emerald-700 ring-emerald-600/25 dark:text-emerald-400 dark:ring-emerald-500/20",
  danger: "bg-rose-500/10 text-rose-700 ring-rose-600/25 dark:text-rose-400 dark:ring-rose-500/20",
  info: "bg-sky-500/10 text-sky-700 ring-sky-600/25 dark:text-sky-400 dark:ring-sky-500/20",
  warning: "bg-amber-500/10 text-amber-700 ring-amber-600/25 dark:text-amber-400 dark:ring-amber-500/20",
  neutral: "bg-slate-500/10 text-slate-600 ring-slate-500/25 dark:text-slate-400 dark:ring-slate-500/20",
};

const DOT_STYLES: Record<BadgeTone, string> = {
  success: "bg-emerald-500 dark:bg-emerald-400",
  danger: "bg-rose-500 dark:bg-rose-400",
  info: "bg-sky-500 dark:bg-sky-400 motion-safe:animate-pulse",
  warning: "bg-amber-500 dark:bg-amber-400",
  neutral: "bg-slate-400",
};

interface BadgeProps {
  status: string;
  tone?: BadgeTone;
  children?: React.ReactNode;
  className?: string;
}

export default function Badge({ status, tone, children, className = "" }: BadgeProps) {
  const resolvedTone = tone ?? STATUS_TONE[status] ?? "neutral";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${TONE_STYLES[resolvedTone]} ${className}`}
    >
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${DOT_STYLES[resolvedTone]}`} />
      {children ?? status}
    </span>
  );
}
