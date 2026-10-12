import { useEffect, useMemo, useState } from "react";
import { CalendarClock } from "lucide-react";
import {
  CronForm,
  cronToForm,
  describeCron,
  EVERY_HOURS,
  formatTime,
  formToCron,
  Frequency,
  isValidCron,
  nextRuns,
  SCHEDULE_TZ_LABEL,
  WEEKDAYS,
} from "../lib/cron";

const FREQUENCIES: { value: Frequency; label: string }[] = [
  { value: "hourly", label: "Каждый час" },
  { value: "daily", label: "Каждый день" },
  { value: "weekly", label: "По дням недели" },
  { value: "monthly", label: "Раз в месяц" },
  { value: "custom", label: "Cron" },
];

const MINUTES = Array.from({ length: 12 }, (_, i) => i * 5);
const MONTH_DAYS = Array.from({ length: 28 }, (_, i) => i + 1);

interface Props {
  value: string;
  onChange: (cron: string) => void;
}

/**
 * Расписание для людей: частота → время → дни, итог словами и ближайшие запуски.
 * Наружу отдаёт обычное cron-выражение; сложное выражение открывается во вкладке «Cron».
 */
export default function CronEditor({ value, onChange }: Props) {
  const [form, setForm] = useState<CronForm>(() => cronToForm(value));

  // Значение поменяли снаружи (другое расписание) — перечитываем форму
  useEffect(() => {
    if (formToCron(form) !== value) setForm(cronToForm(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  function update(patch: Partial<CronForm>) {
    const next = { ...form, ...patch };
    // При переходе в «Cron» подставляем текущее выражение — его удобно поправить руками
    if (patch.frequency === "custom" && form.frequency !== "custom") next.custom = formToCron(form);
    setForm(next);
    onChange(formToCron(next));
  }

  const cron = formToCron(form);
  const noDays = form.frequency === "weekly" && form.weekdays.length === 0;
  const valid = !noDays && isValidCron(cron);
  const description = valid ? describeCron(cron) : null;
  const upcoming = useMemo(() => (valid ? nextRuns(cron, 3) : []), [cron, valid]);

  const time = (
    <input
      type="time"
      value={formatTime(form.hour, form.minute)}
      onChange={(e) => {
        const [h, m] = e.target.value.split(":").map(Number);
        if (!Number.isNaN(h) && !Number.isNaN(m)) update({ hour: h, minute: m });
      }}
      className="input-base w-28 py-1.5"
      aria-label="Время запуска"
      required
    />
  );

  return (
    <div className="space-y-3">
      <div className="inline-flex flex-wrap rounded-lg bg-muted p-0.5" role="radiogroup" aria-label="Как часто">
        {FREQUENCIES.map((f) => (
          <button
            key={f.value}
            type="button"
            role="radio"
            aria-checked={form.frequency === f.value}
            onClick={() => update({ frequency: f.value })}
            className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
              form.frequency === f.value ? "bg-surface text-foreground shadow-panel" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2 text-sm">
        {form.frequency === "hourly" && (
          <>
            <span className="text-muted-foreground">Каждые</span>
            <select value={form.everyHours} onChange={(e) => update({ everyHours: Number(e.target.value) })} className="input-base w-auto py-1.5" aria-label="Интервал в часах">
              {EVERY_HOURS.map((n) => <option key={n} value={n}>{n === 1 ? "1 час" : `${n} ${n < 5 ? "часа" : "часов"}`}</option>)}
            </select>
            <span className="text-muted-foreground">в</span>
            <select value={form.minute} onChange={(e) => update({ minute: Number(e.target.value) })} className="input-base w-auto py-1.5" aria-label="Минута часа">
              {(MINUTES.includes(form.minute) ? MINUTES : [...MINUTES, form.minute].sort((a, b) => a - b)).map((m) => (
                <option key={m} value={m}>:{String(m).padStart(2, "0")}</option>
              ))}
            </select>
            <span className="text-muted-foreground">минут</span>
          </>
        )}

        {form.frequency === "daily" && (
          <>
            <span className="text-muted-foreground">Каждый день в</span>
            {time}
          </>
        )}

        {form.frequency === "weekly" && (
          <>
            <div className="flex flex-wrap gap-1" role="group" aria-label="Дни недели">
              {WEEKDAYS.map((d) => {
                const on = form.weekdays.includes(d.value);
                return (
                  <button
                    key={d.value}
                    type="button"
                    aria-pressed={on}
                    onClick={() => update({ weekdays: on ? form.weekdays.filter((x) => x !== d.value) : [...form.weekdays, d.value].sort((a, b) => a - b) })}
                    className={`h-8 w-10 ${on ? "chip-on" : "chip-off"} justify-center`}
                  >
                    {d.short}
                  </button>
                );
              })}
            </div>
            <div className="flex gap-1">
              <button type="button" className="btn-ghost px-2 py-1 text-xs" onClick={() => update({ weekdays: [1, 2, 3, 4, 5] })}>Будни</button>
              <button type="button" className="btn-ghost px-2 py-1 text-xs" onClick={() => update({ weekdays: [6, 7] })}>Выходные</button>
            </div>
            <span className="text-muted-foreground">в</span>
            {time}
          </>
        )}

        {form.frequency === "monthly" && (
          <>
            <select value={form.monthDay} onChange={(e) => update({ monthDay: Number(e.target.value) })} className="input-base w-auto py-1.5" aria-label="Число месяца">
              {MONTH_DAYS.map((d) => <option key={d} value={d}>{d}-го числа</option>)}
            </select>
            <span className="text-muted-foreground">каждого месяца в</span>
            {time}
          </>
        )}

        {form.frequency === "custom" && (
          <div className="w-full space-y-1">
            <input
              value={form.custom}
              onChange={(e) => update({ custom: e.target.value })}
              className={`input-base w-56 py-1.5 font-mono ${valid ? "" : "border-rose-500 focus-visible:ring-rose-500/40"}`}
              aria-label="Cron-выражение"
              aria-invalid={!valid}
              spellCheck={false}
            />
            <p className="text-xs text-subtle">
              Пять полей через пробел: минута, час, число, месяц, день недели (0 или 7 — воскресенье). Например, <code className="font-mono">*/30 8-18 * * 1-5</code> — каждые полчаса с 8 до 18 по будням.
            </p>
          </div>
        )}
      </div>

      <div className={`rounded-lg border px-3 py-2.5 text-sm ${valid ? "border-border bg-muted/40" : "border-rose-500/40 bg-rose-500/5"}`}>
        {valid ? (
          <div className="flex items-start gap-2.5">
            <CalendarClock className="mt-0.5 h-4 w-4 shrink-0 text-blue-600 dark:text-blue-400" />
            <div className="min-w-0 space-y-0.5">
              <p className="font-medium text-foreground">
                {description ? description[0].toUpperCase() + description.slice(1) : "По cron-выражению"}{" "}
                <span className="font-normal text-muted-foreground">{SCHEDULE_TZ_LABEL}</span>
              </p>
              {upcoming.length > 0 && (
                <p className="text-xs text-muted-foreground">Ближайшие запуски: {upcoming.map((r) => r.label).join(" · ")}</p>
              )}
              <p className="font-mono text-xs text-subtle">cron: {cron}</p>
            </div>
          </div>
        ) : (
          <p className="text-rose-600 dark:text-rose-400">
            {noDays
              ? "Выберите хотя бы один день недели"
              : "Не получается разобрать выражение: нужно пять полей, минута 0–59, час 0–23, число 1–31, месяц 1–12, день недели 0–7"}
          </p>
        )}
      </div>
    </div>
  );
}
