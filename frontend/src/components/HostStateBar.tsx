import { HOST_STATES, StateCounts } from "../lib/hostStates";

interface Props {
  counts: StateCounts;
  /** compact — строка таблицы: тонкая полоса и числа с цветными точками, подписи — во всплывающей подсказке */
  compact?: boolean;
}

// В строке таблицы: сначала итог, потом то, что ещё не закончилось
const COMPACT_ORDER = ["success", "failed", "running", "queued", "waiting", "pending", "cancelled"] as const;

/** Итог запуска по ПК: полоса из долей состояний и числа. */
export default function HostStateBar({ counts, compact }: Props) {
  const total = HOST_STATES.reduce((n, s) => n + (counts[s.key] ?? 0), 0);
  if (total === 0) return null;
  const present = HOST_STATES.filter((s) => counts[s.key]);
  const summary = present.map((s) => `${s.label}: ${counts[s.key]}`).join(", ");
  const bar = (
    <div className={`flex w-full overflow-hidden rounded-full bg-muted ${compact ? "h-1.5" : "h-2"}`} role="img" aria-label={`ПК: ${total}. ${summary}`}>
      {present.map((s) => (
        <span key={s.key} className={`${s.bar} h-full`} style={{ width: `${((counts[s.key] ?? 0) / total) * 100}%` }} />
      ))}
    </div>
  );
  if (!compact) return bar;
  const byKey = Object.fromEntries(HOST_STATES.map((s) => [s.key, s]));
  return (
    <div className="w-36 space-y-1" title={summary}>
      {bar}
      <p className="flex gap-2 text-[11px] leading-none tabular-nums text-muted-foreground" aria-hidden>
        {COMPACT_ORDER.filter((key) => counts[key]).map((key) => (
          <span key={key} className="inline-flex items-center gap-1">
            <span className={`h-1.5 w-1.5 rounded-full ${byKey[key].dot}`} />
            {counts[key]}
          </span>
        ))}
      </p>
    </div>
  );
}
