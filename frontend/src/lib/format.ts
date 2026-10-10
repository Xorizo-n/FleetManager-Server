import type { TaskRun } from "../api/types";

export const OS_OPTIONS = ["windows_10", "windows_11", "windows_server"];

const OS_LABELS: Record<string, string> = {
  windows_10: "Windows 10",
  windows_11: "Windows 11",
  windows_server: "Windows Server",
};

export function osLabel(os: string) {
  return OS_LABELS[os] ?? os;
}

export const STATUS_LABELS: Record<string, string> = {
  online: "online",
  offline: "offline",
  unknown: "неизвестно",
  queued: "в очереди",
  running: "выполняется",
  success: "выполнена",
  failed: "ошибка",
};

export const TASK_TYPE_LABELS: Record<string, string> = {
  playbook: "Плейбук",
  software_scan: "Сканирование ПО",
  host_diagnostic: "Диагностика",
  agent_version_scan: "Проверка версий агента",
  agent_update: "Обновление агента",
};

export const VERSION_LABELS: Record<string, string> = {
  up_to_date: "актуальна",
  outdated: "устарела",
  newer: "новее сервера",
  unknown: "неизвестна",
  no_agent: "нет агента",
};

export const VERSION_TONES: Record<string, "success" | "warning" | "info" | "neutral"> = {
  up_to_date: "success",
  outdated: "warning",
  newer: "info",
  unknown: "neutral",
  no_agent: "neutral",
};

/** Имя плейбука без папок и расширения: playbooks/install/install_7zip.yml -> install_7zip */
export function playbookShortName(path: string) {
  return path.split("/").pop()?.replace(/\.(yml|yaml)$/, "") ?? path;
}

export function taskTitle(task: Pick<TaskRun, "task_type" | "playbook_name">) {
  if (task.task_type === "playbook" && task.playbook_name) return playbookShortName(task.playbook_name);
  return TASK_TYPE_LABELS[task.task_type] ?? task.task_type;
}

export function hostLabel(host: { hostname: string | null; ip_address: string | null; id?: string }) {
  return host.hostname || host.ip_address || host.id || "—";
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "никогда";
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60_000) return "только что";
  const min = Math.floor(ms / 60_000);
  if (min < 60) return `${min} мин назад`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} ч назад`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day} дн назад`;
  return new Date(iso).toLocaleDateString("ru-RU");
}

export function formatDateTime(iso: string | null | undefined) {
  return iso ? new Date(iso).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" }) : "—";
}

export function formatDuration(startIso: string | null, endIso: string | null) {
  if (!startIso) return "—";
  const ms = (endIso ? new Date(endIso).getTime() : Date.now()) - new Date(startIso).getTime();
  const sec = Math.max(0, Math.round(ms / 1000));
  if (sec < 60) return `${sec} с`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} мин ${sec % 60} с`;
  return `${Math.floor(min / 60)} ч ${min % 60} мин`;
}

export function formatSize(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} ГБ`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} МБ`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} КБ`;
  return `${bytes} Б`;
}

export function formatRam(bytes: number | null | undefined): string {
  if (!bytes) return "—";
  const gb = bytes / 1024 ** 3;
  return gb >= 1 ? `${Math.round(gb)} ГБ` : `${Math.round(bytes / 1024 ** 2)} МБ`;
}

/** Склонение: plural(3, "хост", "хоста", "хостов") -> "3 хоста" */
export function plural(n: number, one: string, few: string, many: string) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  const word = mod10 === 1 && mod100 !== 11 ? one : mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14) ? few : many;
  return `${n} ${word}`;
}

export const pcCount = (n: number) => plural(n, "ПК", "ПК", "ПК");

export function apiError(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg).replace(/^Value error, /, "");
  return fallback;
}
