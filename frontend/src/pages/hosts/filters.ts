import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import type { Host, VersionStatus } from "../../api/types";
import { GroupTree, NO_GROUP } from "../../lib/groupTree";

// Фильтры реестра хостов живут в адресной строке: ссылкой можно поделиться,
// а счётчики дашборда ведут сразу на отфильтрованный список.

export interface HostFilters {
  q: string;
  group: string;
  status: string;
  agent: string;
  os: string;
  checked: string;
}

const FILTER_KEYS: (keyof HostFilters)[] = ["q", "group", "status", "agent", "os", "checked"];

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

export function filterHosts(hosts: Host[], filters: HostFilters, tree: GroupTree, versionOf: (h: Host) => VersionStatus) {
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
    if (filters.os && h.os !== filters.os) return false;
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
