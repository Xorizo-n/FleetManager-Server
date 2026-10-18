import { useMemo } from "react";
import { ChevronDown, SlidersHorizontal, X } from "lucide-react";
import type { Host, VersionStatus } from "../../api/types";
import SearchInput from "../../components/ui/SearchInput";
import { GroupTree } from "../../lib/groupTree";
import { OS_OPTIONS, osLabel } from "../../lib/format";
import {
  ACTIVATION_FILTERS,
  AGENT_FILTERS,
  ALERT_FILTERS,
  CHECKED_FILTERS,
  DEVICE_FILTERS,
  HostFilters,
  filterHosts,
} from "./filters";

type FilterKey = Exclude<keyof HostFilters, "q" | "group" | "wallpaper">;

interface FilterDef {
  key: FilterKey;
  label: string;
  options: { value: string; label: string }[];
}

// Фильтры по смыслу: что с ПК сейчас, что на нём стоит, что с рабочим местом
const SECTIONS: { title: string; filters: FilterDef[] }[] = [
  {
    title: "Состояние",
    filters: [
      {
        key: "status",
        label: "Статус",
        options: [
          { value: "online", label: "online" },
          { value: "offline", label: "offline" },
          { value: "unknown", label: "неизвестно" },
        ],
      },
      { key: "checked", label: "Проверен", options: CHECKED_FILTERS },
      { key: "alerts", label: "Алерты", options: ALERT_FILTERS.map((o) => ({ value: o.value, label: o.label.replace(/^Алерты /, "") })) },
    ],
  },
  {
    title: "Агент и система",
    filters: [
      { key: "agent", label: "Агент", options: AGENT_FILTERS },
      { key: "os", label: "ОС", options: OS_OPTIONS.map((o) => ({ value: o, label: osLabel(o) })) },
    ],
  },
  {
    title: "Рабочее место",
    filters: [
      { key: "devices", label: "Оборудование и диски", options: DEVICE_FILTERS },
      { key: "activation", label: "Активация", options: ACTIVATION_FILTERS },
    ],
  },
];

const ALL_FILTERS = SECTIONS.flatMap((s) => s.filters);

interface FilterPanelProps {
  hosts: Host[];
  filters: HostFilters;
  setFilter: (key: keyof HostFilters, value: string) => void;
  reset: () => void;
  tree: GroupTree;
  versionOf: (h: Host) => VersionStatus;
  alertCounts: Map<string, number>;
  open: boolean;
  onToggle: (open: boolean) => void;
}

/**
 * Поиск, кнопка «Фильтры» и выбранные фильтры чипами. Сами фильтры — в раскрывающейся
 * панели по разделам; у каждого варианта — сколько ПК он оставит при остальных фильтрах.
 */
export default function FilterPanel({ hosts, filters, setFilter, reset, tree, versionOf, alertCounts, open, onToggle }: FilterPanelProps) {
  const active = ALL_FILTERS.filter((f) => filters[f.key]);
  const activeCount = active.length + (filters.wallpaper ? 1 : 0);

  // Счётчики считаются, только пока панель открыта: ~35 вариантов × все ПК
  const counts = useMemo(() => {
    if (!open) return null;
    const result = new Map<string, number>();
    // Алерты не считаются: сводка алертов загружена за один выбранный период
    for (const f of ALL_FILTERS.filter((x) => x.key !== "alerts")) {
      for (const o of f.options) {
        result.set(`${f.key}:${o.value}`, filterHosts(hosts, { ...filters, [f.key]: o.value }, tree, versionOf, alertCounts).length);
      }
    }
    return result;
  }, [open, hosts, filters, tree, versionOf, alertCounts]);

  const optionLabel = (f: FilterDef) => f.options.find((o) => o.value === filters[f.key])?.label ?? filters[f.key];

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <SearchInput value={filters.q} onChange={(v) => setFilter("q", v)} placeholder="Имя, IP, серийный номер, комментарий" className="min-w-[220px] grow basis-full sm:basis-0" />
        <select value={filters.group} onChange={(e) => setFilter("group", e.target.value)} className="input-base w-auto min-w-0 flex-1 py-2 sm:max-w-[14rem] sm:flex-none xl:hidden" aria-label="Группа">
          <option value="">Все группы</option>
          {tree.options.map((g) => <option key={g.id} value={g.id}>{g.label}</option>)}
        </select>
        <button
          type="button"
          className={`btn-secondary ${open ? "border-blue-500 dark:border-blue-500" : ""}`}
          onClick={() => onToggle(!open)}
          aria-expanded={open}
          aria-controls="host-filter-panel"
        >
          <SlidersHorizontal className="h-4 w-4" />
          Фильтры
          {activeCount > 0 && (
            <span className="min-w-5 rounded-full bg-blue-600 px-1.5 text-center text-xs font-semibold tabular-nums text-white">{activeCount}</span>
          )}
          <ChevronDown className={`h-4 w-4 text-subtle transition-transform duration-200 ${open ? "rotate-180" : ""}`} />
        </button>
      </div>

      {open && (
        <div id="host-filter-panel" className="surface-panel grid gap-x-8 gap-y-5 md:grid-cols-3">
          {SECTIONS.map((section) => (
            <section key={section.title} className="min-w-0 space-y-3">
              <h3 className="border-b border-border pb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{section.title}</h3>
              {section.filters.map((f) => (
                <fieldset key={f.key} className="min-w-0">
                  <legend className="mb-1.5 text-xs font-medium text-foreground">{f.label}</legend>
                  <div className="flex flex-wrap gap-1.5">
                    {f.options.map((o) => {
                      const on = filters[f.key] === o.value;
                      const count = counts?.get(`${f.key}:${o.value}`);
                      return (
                        <button
                          key={o.value}
                          type="button"
                          aria-pressed={on}
                          onClick={() => setFilter(f.key, on ? "" : o.value)}
                          className={`${on ? "chip-on" : "chip-off"} gap-1.5 ${!on && count === 0 ? "opacity-50" : ""}`}
                          title={on ? "Нажмите ещё раз, чтобы снять" : undefined}
                        >
                          {o.label}
                          {count !== undefined && <span className={`tabular-nums ${on ? "" : "text-subtle"}`}>{count}</span>}
                        </button>
                      );
                    })}
                  </div>
                </fieldset>
              ))}
            </section>
          ))}
        </div>
      )}

      {(activeCount > 0 || filters.group) && (
        <div className="flex flex-wrap items-center gap-1.5" aria-label="Выбранные фильтры">
          {active.map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => setFilter(f.key, "")}
              className="chip-on gap-1"
              aria-label={`Снять фильтр «${f.label}: ${optionLabel(f)}»`}
            >
              <span className="font-normal opacity-75">{f.label}:</span> {optionLabel(f)}
              <X className="h-3 w-3" />
            </button>
          ))}
          {filters.wallpaper && (
            <button type="button" onClick={() => setFilter("wallpaper", "")} className="chip-on gap-1" title="Фильтр со страницы «Обои»" aria-label="Снять фильтр по обоям">
              <span className="font-normal opacity-75">Обои:</span> выбранное изображение
              <X className="h-3 w-3" />
            </button>
          )}
          <button type="button" onClick={reset} className="btn-ghost btn-sm">
            Сбросить всё
          </button>
        </div>
      )}
    </div>
  );
}
