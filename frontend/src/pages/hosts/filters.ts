import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import type { Host, VersionStatus } from "../../api/types";
import { GroupTree, NO_GROUP } from "../../lib/groupTree";
import { hasActivationProblem, kmsUnreachable, notActivated } from "../../lib/activation";
import { presence } from "../../lib/devices";
import { DISK_CRITICAL_PERCENT, DISK_WARN_PERCENT, diskUsedPercent, fullestDisk } from "../../lib/hardware";

// Фильтры реестра хостов живут в адресной строке: ссылкой можно поделиться,
// а счётчики дашборда ведут сразу на отфильтрованный список.

export interface HostFilters {
  q: string;
  group: string;
  status: string;
  agent: string;
  os: string;
  checked: string;
  alerts: string;
  activation: string;
  devices: string;
  /** sha256 обоев (рабочий стол или экран блокировки), «path:…» — файл без хэша, «none» — не заданы */
  wallpaper: string;
  /** id тега, «none» — без тега, «manual» — тег поставлен вручную */
  tag: string;
}

const FILTER_KEYS: (keyof HostFilters)[] = ["q", "group", "status", "agent", "os", "checked", "alerts", "activation", "devices", "wallpaper", "tag"];

export const AGENT_FILTERS: { value: string; label: string }[] = [
  { value: "with", label: "С агентом" },
  { value: "without", label: "Без агента" },
  { value: "outdated", label: "Версия устарела" },
  { value: "up_to_date", label: "Версия актуальна" },
  { value: "unknown", label: "Версия неизвестна" },
];

export const CHECKED_FILTERS: { value: string; label: string }[] = [
  { value: "24h", label: "За 24 часа" },
  { value: "7d", label: "За 7 дней" },
  { value: "older", label: "Давно (> 7 дней)" },
  { value: "never", label: "Никогда" },
];

// Период фильтра «Алерты» в днях; «all» — за всё время
export const ALERT_FILTERS: { value: string; label: string; days: number }[] = [
  { value: "7", label: "Алерты за 7 дней", days: 7 },
  { value: "30", label: "Алерты за 30 дней", days: 30 },
  { value: "all", label: "Алерты за всё время", days: 3650 },
];

export const ACTIVATION_FILTERS: { value: string; label: string; match: (h: Host) => boolean }[] = [
  { value: "problem", label: "Есть проблемы", match: hasActivationProblem },
  { value: "windows", label: "Windows не активирован", match: (h) => notActivated(h.activation_windows) },
  { value: "office", label: "Office не активирован", match: (h) => notActivated(h.activation_office) },
  { value: "expiring", label: "Активация истекает", match: (h) => h.activation_windows === "expiring" || h.activation_office === "expiring" },
  { value: "kms", label: "KMS недоступен", match: kmsUnreachable },
  {
    value: "ok",
    label: "Всё активировано",
    match: (h) => !!h.license_activation && [h.activation_windows, h.activation_office].every((s) => !s || s === "licensed"),
  },
  { value: "unknown", label: "Нет данных", match: (h) => !h.license_activation },
];

const DAY = 86_400_000;
const fullestPercent = (h: Host) => {
  const disk = fullestDisk(h);
  return disk ? diskUsedPercent(disk) : 0;
};
const changedWithin = (h: Host, days: number) => !!h.hw_changed_at && Date.now() - new Date(h.hw_changed_at).getTime() <= days * DAY;

export const DEVICE_FILTERS: { value: string; label: string; match: (h: Host) => boolean }[] = [
  { value: "noinput", label: "Нет клавиатуры или мыши", match: (h) => presence(h, "keyboard") === "missing" || presence(h, "mouse") === "missing" },
  { value: "nomonitor", label: "Нет монитора", match: (h) => presence(h, "monitor") === "missing" },
  { value: "diskfull", label: `Диск заполнен на ${DISK_CRITICAL_PERCENT}% и больше`, match: (h) => fullestPercent(h) >= DISK_CRITICAL_PERCENT },
  { value: "diskwarn", label: `Диск заполнен на ${DISK_WARN_PERCENT}% и больше`, match: (h) => fullestPercent(h) >= DISK_WARN_PERCENT },
  { value: "pending", label: "Устройство пропало недавно", match: (h) => (h.hw_pending_devices ?? []).some((p) => p.missing) },
  { value: "changed7", label: "Изменения за 7 дней", match: (h) => changedWithin(h, 7) },
  { value: "changed30", label: "Изменения за 30 дней", match: (h) => changedWithin(h, 30) },
  { value: "unknown", label: "Нет данных", match: (h) => !h.hw_components },
];

function showsWallpaper(h: Host, value: string) {
  const state = h.wallpaper_state;
  if (!state) return false;
  // Несколько хэшей через запятую — варианты одной картинки (lib/wallpapers.ts, currentDistribution)
  const hashes = new Set(value.split(","));
  return [state.desktop, state.lock_screen].some((c) =>
    value === "none" ? !c : value.startsWith("path:") ? !!c && !c.sha256 && c.path.toLowerCase() === value.slice(5).toLowerCase() : !!c?.sha256 && hashes.has(c.sha256),
  );
}

export const alertDays = (value: string) => ALERT_FILTERS.find((f) => f.value === value)?.days ?? 7;

export function useHostFilters() {
  const [params, setParams] = useSearchParams();
  const filters = useMemo(
    () => Object.fromEntries(FILTER_KEYS.map((k) => [k, params.get(k) ?? ""])) as unknown as HostFilters,
    [params],
  );
  const setFilter = (key: keyof HostFilters, value: string) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value) next.set(key, value);
        else next.delete(key);
        return next;
      },
      { replace: true },
    );
  const reset = () =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        FILTER_KEYS.forEach((k) => next.delete(k));
        return next;
      },
      { replace: true },
    );
  const activeCount = FILTER_KEYS.filter((k) => k !== "group" && filters[k]).length;
  return { filters, setFilter, reset, activeCount };
}

export function filterHosts(
  hosts: Host[],
  filters: HostFilters,
  tree: GroupTree,
  versionOf: (h: Host) => VersionStatus,
  alertCounts: Map<string, number>,
) {
  const q = filters.q.trim().toLowerCase();
  const groupSet = filters.group && filters.group !== NO_GROUP ? tree.descendants(filters.group) : null;
  const now = Date.now();
  const DAY = 86_400_000;
  return hosts.filter((h) => {
    if (q) {
      const haystack = [h.hostname, h.ip_address, h.comment, h.hw_serial_number, h.hw_model].filter(Boolean).join(" ").toLowerCase();
      if (!haystack.includes(q)) return false;
    }
    if (filters.group === NO_GROUP && h.group_id && tree.byId.has(h.group_id)) return false;
    if (groupSet && (!h.group_id || !groupSet.has(h.group_id))) return false;
    if (filters.status && h.status !== filters.status) return false;
    if (filters.alerts && !alertCounts.get(h.id)) return false;
    if (filters.os && h.os !== filters.os) return false;
    if (filters.tag === "none" ? !!h.tag_id : filters.tag === "manual" ? !h.tag_manual : filters.tag && h.tag_id !== filters.tag) return false;
    if (filters.wallpaper && !showsWallpaper(h, filters.wallpaper)) return false;
    if (filters.devices && !DEVICE_FILTERS.find((f) => f.value === filters.devices)?.match(h)) return false;
    if (filters.activation && !ACTIVATION_FILTERS.find((f) => f.value === filters.activation)?.match(h)) return false;
    if (filters.agent) {
      if (filters.agent === "with" && !h.has_agent) return false;
      if (filters.agent === "without" && h.has_agent) return false;
      if (!["with", "without"].includes(filters.agent) && versionOf(h) !== filters.agent) return false;
    }
    if (filters.checked) {
      const age = h.last_checked_at ? now - new Date(h.last_checked_at).getTime() : null;
      if (filters.checked === "never" && age !== null) return false;
      if (filters.checked === "24h" && (age === null || age > DAY)) return false;
      if (filters.checked === "7d" && (age === null || age > 7 * DAY)) return false;
      if (filters.checked === "older" && (age === null || age <= 7 * DAY)) return false;
    }
    return true;
  });
}
