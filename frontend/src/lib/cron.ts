export const CRON_PRESETS: { label: string; value: string }[] = [
  { label: "Каждый день в 03:00", value: "0 3 * * *" },
  { label: "По будням в 21:30", value: "30 21 * * 1-5" },
  { label: "Каждый понедельник в 03:00", value: "0 3 * * 1" },
  { label: "Каждый час", value: "0 * * * *" },
];

const DAYS: Record<string, string> = {
  "0": "каждое воскресенье", "7": "каждое воскресенье", "1": "каждый понедельник", "2": "каждый вторник", "3": "каждую среду",
  "4": "каждый четверг", "5": "каждую пятницу", "6": "каждую субботу", "1-5": "по будням", "0,6": "по выходным", "6,0": "по выходным",
};

/** Человекочитаемое описание для простых cron-выражений; остальные показываются как есть. */
export function describeCron(expr: string): string | null {
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return null;
  const [minute, hour, dom, month, dow] = parts;
  if (dom !== "*" || month !== "*" || !/^\d+$/.test(minute)) return null;
  const mm = minute.padStart(2, "0");
  if (hour === "*") return dow === "*" ? `каждый час в :${mm}` : null;
  if (!/^\d+$/.test(hour)) return null;
  const time = `${hour.padStart(2, "0")}:${mm}`;
  if (dow === "*") return `каждый день в ${time}`;
  return DAYS[dow] ? `${DAYS[dow]} в ${time}` : null;
}

export function isCronLike(expr: string) {
  return expr.trim().split(/\s+/).length === 5;
}
