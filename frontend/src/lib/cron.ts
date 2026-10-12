// Расписания: cron ↔ понятная форма, описание по-русски и ближайшие запуски.
//
// Сервер считает cron по времени Екатеринбурга (SCHEDULE_TIMEZONE, по умолчанию
// Asia/Yekaterinburg, UTC+5 без перехода на летнее время), поэтому ближайшие
// запуски здесь считаются по тому же поясу, а не по поясу браузера.

export const SCHEDULE_TZ_OFFSET_MINUTES = 5 * 60;
export const SCHEDULE_TZ_LABEL = "по времени Екатеринбурга (UTC+5)";

export type Frequency = "hourly" | "daily" | "weekly" | "monthly" | "custom";

export interface CronForm {
  frequency: Frequency;
  minute: number;
  hour: number;
  /** Каждые N часов (hourly) */
  everyHours: number;
  /** Дни недели 1 (пн) … 7 (вс) */
  weekdays: number[];
  /** Число месяца (monthly) */
  monthDay: number;
  /** Своё выражение (custom) */
  custom: string;
}

export const EVERY_HOURS = [1, 2, 3, 4, 6, 8, 12];
export const WEEKDAYS: { value: number; short: string }[] = [
  { value: 1, short: "Пн" }, { value: 2, short: "Вт" }, { value: 3, short: "Ср" }, { value: 4, short: "Чт" },
  { value: 5, short: "Пт" }, { value: 6, short: "Сб" }, { value: 7, short: "Вс" },
];

export const DEFAULT_CRON = "0 3 * * *";

export const DEFAULT_FORM: CronForm = { frequency: "daily", minute: 0, hour: 3, everyHours: 1, weekdays: [1, 2, 3, 4, 5], monthDay: 1, custom: DEFAULT_CRON };

const pad = (n: number) => String(n).padStart(2, "0");
export const formatTime = (hour: number, minute: number) => `${pad(hour)}:${pad(minute)}`;

/** Дни недели в cron: 1-5, 0,6 или список; воскресенье — 0. */
function weekdaysToCron(days: number[]): string {
  const sorted = [...new Set(days)].sort((a, b) => a - b);
  const key = sorted.join(",");
  if (key === "1,2,3,4,5") return "1-5";
  if (key === "6,7") return "0,6";
  return sorted.map((d) => (d === 7 ? 0 : d)).sort((a, b) => a - b).join(",");
}

export function formToCron(form: CronForm): string {
  const { minute: m, hour: h } = form;
  switch (form.frequency) {
    case "hourly":
      return form.everyHours > 1 ? `${m} */${form.everyHours} * * *` : `${m} * * * *`;
    case "daily":
      return `${m} ${h} * * *`;
    case "weekly":
      return `${m} ${h} * * ${weekdaysToCron(form.weekdays)}`;
    case "monthly":
      return `${m} ${h} ${form.monthDay} * *`;
    default:
      return form.custom.trim().replace(/\s+/g, " ");
  }
}

const NUM = /^\d{1,2}$/;

/** Выражение → форма. Что не укладывается в простые варианты, открывается как «Cron». */
export function cronToForm(expr: string): CronForm {
  const base: CronForm = { ...DEFAULT_FORM, custom: expr.trim() };
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5 || !parse(expr)) return { ...base, frequency: "custom" };
  const [mi, ho, dom, mon, dow] = parts;
  if (!NUM.test(mi) || mon !== "*") return { ...base, frequency: "custom" };
  const minute = Number(mi);

  if (dom === "*" && dow === "*") {
    if (ho === "*") return { ...base, frequency: "hourly", minute, everyHours: 1 };
    const every = ho.match(/^\*\/(\d+)$/);
    if (every && EVERY_HOURS.includes(Number(every[1]))) return { ...base, frequency: "hourly", minute, everyHours: Number(every[1]) };
    if (NUM.test(ho)) return { ...base, frequency: "daily", minute, hour: Number(ho) };
    return { ...base, frequency: "custom" };
  }
  if (!NUM.test(ho)) return { ...base, frequency: "custom" };
  const hour = Number(ho);
  if (dom === "*") {
    const days = parse(`0 0 * * ${dow}`)?.dow;
    if (!days) return { ...base, frequency: "custom" };
    return { ...base, frequency: "weekly", minute, hour, weekdays: [...days].map((d) => (d === 0 ? 7 : d)).sort((a, b) => a - b) };
  }
  if (dow === "*" && NUM.test(dom) && Number(dom) >= 1 && Number(dom) <= 28) {
    return { ...base, frequency: "monthly", minute, hour, monthDay: Number(dom) };
  }
  return { ...base, frequency: "custom" };
}

// ---------- разбор cron (минута час день месяц день_недели) ----------

interface Parsed {
  minute: Set<number>;
  hour: Set<number>;
  dom: Set<number>;
  month: Set<number>;
  dow: Set<number>;
  domAny: boolean;
  dowAny: boolean;
}

function parseField(field: string, min: number, max: number): Set<number> | null {
  const out = new Set<number>();
  for (const part of field.split(",")) {
    const m = part.match(/^(\*|\d+)(?:-(\d+))?(?:\/(\d+))?$/);
    if (!m) return null;
    let from = m[1] === "*" ? min : Number(m[1]);
    let to = m[1] === "*" ? max : m[2] !== undefined ? Number(m[2]) : m[3] !== undefined ? max : from;
    const step = m[3] !== undefined ? Number(m[3]) : 1;
    if (from < min || to > max || from > to || step < 1) return null;
    for (let v = from; v <= to; v += step) out.add(v);
  }
  return out.size ? out : null;
}

export function parse(expr: string): Parsed | null {
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return null;
  const minute = parseField(parts[0], 0, 59);
  const hour = parseField(parts[1], 0, 23);
  const dom = parseField(parts[2], 1, 31);
  const month = parseField(parts[3], 1, 12);
  const dowRaw = parseField(parts[4], 0, 7);
  if (!minute || !hour || !dom || !month || !dowRaw) return null;
  const dow = new Set([...dowRaw].map((d) => (d === 7 ? 0 : d)));
  return { minute, hour, dom, month, dow, domAny: parts[2] === "*", dowAny: parts[4] === "*" };
}

export const isValidCron = (expr: string) => parse(expr) !== null;

/** Ближайшие запуски (по времени Екатеринбурга) — как настенное время, без перевода в пояс браузера. */
export function nextRuns(expr: string, count = 3, now = Date.now()): { date: Date; label: string }[] {
  const p = parse(expr);
  if (!p) return [];
  const offset = SCHEDULE_TZ_OFFSET_MINUTES * 60_000;
  // «Настенное» время Екатеринбурга в полях UTC объекта Date
  const wall = new Date(Math.floor((now + offset) / 60_000) * 60_000 + 60_000);
  const result: { date: Date; label: string }[] = [];
  const limit = 366 * 24 * 60 * 2; // два года по минутам — заведомо больше любого цикла cron
  for (let i = 0; i < limit && result.length < count; i++) {
    const t = new Date(wall.getTime() + i * 60_000);
    if (!p.minute.has(t.getUTCMinutes()) || !p.hour.has(t.getUTCHours()) || !p.month.has(t.getUTCMonth() + 1)) continue;
    const domOk = p.dom.has(t.getUTCDate());
    const dowOk = p.dow.has(t.getUTCDay());
    // Как в cron: если ограничены и число, и день недели — достаточно любого из них
    const dayOk = p.domAny || p.dowAny ? domOk && dowOk : domOk || dowOk;
    if (!dayOk) continue;
    result.push({ date: new Date(t.getTime() - offset), label: wallLabel(t) });
  }
  return result;
}

const DOW_SHORT = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];
const MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
function wallLabel(t: Date) {
  return `${DOW_SHORT[t.getUTCDay()]}, ${t.getUTCDate()} ${MONTHS[t.getUTCMonth()]}, ${formatTime(t.getUTCHours(), t.getUTCMinutes())}`;
}

// ---------- описание по-русски ----------

const DAY_NAMES_DAT = ["воскресеньям", "понедельникам", "вторникам", "средам", "четвергам", "пятницам", "субботам"];

function hoursWord(n: number) {
  const mod10 = n % 10, mod100 = n % 100;
  return mod10 === 1 && mod100 !== 11 ? "час" : mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14) ? "часа" : "часов";
}

/** «по понедельникам и пятницам в 03:00»; null — если выражение не простое (тогда показываем cron как есть). */
export function describeCron(expr: string): string | null {
  const form = cronToForm(expr);
  const time = formatTime(form.hour, form.minute);
  switch (form.frequency) {
    case "hourly":
      return form.everyHours === 1
        ? `каждый час в :${pad(form.minute)}`
        : `каждые ${form.everyHours} ${hoursWord(form.everyHours)} в :${pad(form.minute)}`;
    case "daily":
      return `каждый день в ${time}`;
    case "weekly": {
      const days = form.weekdays;
      const key = days.join(",");
      if (key === "1,2,3,4,5") return `по будням в ${time}`;
      if (key === "6,7") return `по выходным в ${time}`;
      if (key === "1,2,3,4,5,6,7") return `каждый день в ${time}`;
      const names = days.map((d) => DAY_NAMES_DAT[d % 7]);
      const list = names.length > 1 ? `${names.slice(0, -1).join(", ")} и ${names[names.length - 1]}` : names[0];
      return `по ${list} в ${time}`;
    }
    case "monthly":
      return `${form.monthDay}-го числа каждого месяца в ${time}`;
    default:
      return null;
  }
}
