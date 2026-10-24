import type { HostState, TaskRun } from "../api/types";

/** Состояние ПК в запуске: подписи, цвета и порядок — от того, что требует внимания, к остальному. */
export const HOST_STATES: { key: HostState; label: string; short: string; bar: string; dot: string; text: string }[] = [
  { key: "failed", label: "Ошибка", short: "ошибка", bar: "bg-rose-500", dot: "bg-rose-500", text: "text-rose-600 dark:text-rose-400" },
  { key: "running", label: "Выполняется", short: "идёт", bar: "bg-sky-500", dot: "bg-sky-500 motion-safe:animate-pulse", text: "text-sky-600 dark:text-sky-400" },
  { key: "queued", label: "В очереди", short: "в очереди", bar: "bg-sky-300 dark:bg-sky-700", dot: "bg-sky-300 dark:bg-sky-600", text: "text-muted-foreground" },
  { key: "waiting", label: "Ждут включения", short: "ждут ПК", bar: "bg-violet-400 dark:bg-violet-500", dot: "bg-violet-500", text: "text-violet-700 dark:text-violet-300" },
  { key: "pending", label: "Ждут предыдущий плейбук", short: "ждут плейбук", bar: "bg-slate-300 dark:bg-slate-600", dot: "bg-slate-400", text: "text-muted-foreground" },
  { key: "success", label: "Успешно", short: "успешно", bar: "bg-emerald-500", dot: "bg-emerald-500", text: "text-emerald-600 dark:text-emerald-400" },
  { key: "cancelled", label: "Отменены", short: "отменено", bar: "bg-slate-200 dark:bg-slate-700", dot: "bg-slate-300 dark:bg-slate-600", text: "text-subtle" },
];

export const HOST_STATE_INFO = Object.fromEntries(HOST_STATES.map((s) => [s.key, s])) as Record<HostState, (typeof HOST_STATES)[number]>;

/** Состояние ПК в задаче; у задач без host_states (старые, диагностика) — статус задачи целиком. */
export function hostStateOf(task: Pick<TaskRun, "status" | "host_states">, hostId: string): HostState {
  const own = task.host_states?.[hostId];
  if (own) return own === "ready" ? "queued" : own;
  switch (task.status) {
    case "success":
    case "failed":
    case "running":
    case "queued":
    case "waiting":
    case "pending":
    case "cancelled":
      return task.status;
    default:
      return "cancelled";
  }
}

export type StateCounts = Partial<Record<HostState, number>>;

export function countHostStates(task: Pick<TaskRun, "status" | "host_states" | "host_ids">): StateCounts {
  const counts: StateCounts = {};
  for (const id of task.host_ids) {
    const state = hostStateOf(task, id);
    counts[state] = (counts[state] ?? 0) + 1;
  }
  return counts;
}

/** Статус для показа: запуск, где часть ПК прошла, а часть нет, — «частично», а не «ошибка». */
export function displayStatus(task: Pick<TaskRun, "status" | "host_states" | "host_ids">): string {
  if (task.status !== "failed" || !task.host_states || task.host_ids.length < 2) return task.status;
  return countHostStates(task).success ? "partial" : "failed";
}

/** Сколько ПК уже закончили (успешно, с ошибкой или отменены). */
export function finishedCount(counts: StateCounts): number {
  return (counts.success ?? 0) + (counts.failed ?? 0) + (counts.cancelled ?? 0);
}
