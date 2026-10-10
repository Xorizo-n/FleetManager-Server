import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { useWindowVirtualizer } from "@tanstack/react-virtual";
import { ArrowDown, ArrowUp, BellRing, DoorOpen } from "lucide-react";
import type { Host, VersionStatus } from "../../api/types";
import type { GroupTree } from "../../lib/groupTree";
import Checkbox from "../../components/ui/Checkbox";
import { formatRam, hostLabel, osLabel, pcCount, relativeTime, VERSION_LABELS } from "../../lib/format";

export type ColumnSet = "main" | "hardware";
type SortKey = "name" | "ip" | "status" | "agent" | "checked";

interface Props {
  hosts: Host[];
  tree: GroupTree;
  versionOf: (h: Host) => VersionStatus;
  columns: ColumnSet;
  grouped: boolean;
  selectable: boolean;
  selected: Set<string>;
  onToggle: (ids: string[]) => void;
  onOpen: (host: Host) => void;
  alertCounts?: Map<string, number>;
}

type Row = { kind: "group"; key: string; label: string; hosts: Host[] } | { kind: "host"; host: Host };

const STATUS_ORDER: Record<string, number> = { online: 0, unknown: 1, offline: 2 };
const VERSION_ORDER: Record<string, number> = { outdated: 0, unknown: 1, newer: 2, up_to_date: 3, no_agent: 4 };
const collator = new Intl.Collator("ru", { numeric: true });

// Одна сетка колонок на всю таблицу: ширина не «прыгает» между аудиториями
// В узкой таблице (< 880px) колонка ОС скрывается, чтобы не было горизонтальной прокрутки
const GRID: Record<ColumnSet, { wide: string; compact: string }> = {
  main: {
    wide: "2.25rem minmax(11rem,1.4fr) 8.5rem 6.5rem minmax(9rem,1fr) 7rem 7.5rem",
    compact: "2.25rem minmax(9rem,1.4fr) 7.5rem 6rem minmax(8rem,1fr) 6.5rem",
  },
  hardware: {
    wide: "2.25rem minmax(11rem,1.2fr) minmax(10rem,1.2fr) minmax(10rem,1.2fr) 4.5rem minmax(8rem,1fr) minmax(9rem,1fr)",
    compact: "2.25rem minmax(9rem,1fr) minmax(8rem,1fr) minmax(8rem,1.2fr) 4rem minmax(7rem,1fr)",
  },
};

/** Реестр хостов: одна виртуализованная таблица, разделители по аудиториям. */
export default function HostTable({ hosts, tree, versionOf, columns, grouped, selectable, selected, onToggle, onOpen, alertCounts }: Props) {
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "name", desc: false });
  const listRef = useRef<HTMLDivElement>(null);
  const shellRef = useRef<HTMLDivElement>(null);
  const [scrollMargin, setScrollMargin] = useState(0);
  const [layout, setLayout] = useState<"mobile" | "compact" | "wide">("wide");

  useLayoutEffect(() => {
    setScrollMargin(listRef.current?.offsetTop ?? 0);
  });

  useLayoutEffect(() => {
    if (!shellRef.current) return;
    const observer = new ResizeObserver(([entry]) => {
      const width = entry.contentRect.width;
      setLayout(width < 560 ? "mobile" : width < 880 ? "compact" : "wide");
    });
    observer.observe(shellRef.current);
    return () => observer.disconnect();
  }, []);
  const compact = layout !== "wide";
  const mobile = layout === "mobile";
  // На телефоне — только имя (с IP и агентом второй строкой) и статус
  const grid = mobile ? "2.25rem minmax(0,1fr) auto" : compact ? GRID[columns].compact : GRID[columns].wide;

  const rows = useMemo<Row[]>(() => {
    const compare = (a: Host, b: Host) => {
      let result = 0;
      if (sort.key === "ip") result = collator.compare(a.ip_address ?? "", b.ip_address ?? "");
      else if (sort.key === "status") result = (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9);
      else if (sort.key === "agent") result = (VERSION_ORDER[versionOf(a)] ?? 9) - (VERSION_ORDER[versionOf(b)] ?? 9);
      else if (sort.key === "checked") result = (b.last_checked_at ?? "").localeCompare(a.last_checked_at ?? "");
      if (result === 0) result = collator.compare(hostLabel(a), hostLabel(b));
      return sort.desc ? -result : result;
    };
    const sorted = [...hosts].sort(compare);
    if (!grouped) return sorted.map((host) => ({ kind: "host", host }));
    const byGroup = new Map<string, Host[]>();
    for (const h of sorted) {
      const key = h.group_id && tree.byId.has(h.group_id) ? h.group_id : "";
      if (!byGroup.has(key)) byGroup.set(key, []);
      byGroup.get(key)!.push(h);
    }
    const result: Row[] = [];
    [...byGroup.entries()]
      .map(([key, list]) => ({ key, label: tree.pathOf(key || null), list }))
      .sort((a, b) => (a.key === "" ? 1 : b.key === "" ? -1 : collator.compare(a.label, b.label)))
      .forEach(({ key, label, list }) => {
        result.push({ kind: "group", key: key || "none", label, hosts: list });
        list.forEach((host) => result.push({ kind: "host", host }));
      });
    return result;
  }, [hosts, grouped, sort, tree, versionOf]);

  const virtualizer = useWindowVirtualizer({
    count: rows.length,
    estimateSize: (i) => (rows[i].kind === "group" ? 36 : 44),
    overscan: 15,
    scrollMargin,
  });

  const allIds = useMemo(() => hosts.map((h) => h.id), [hosts]);
  const selectedVisible = allIds.filter((id) => selected.has(id)).length;

  const header = (key: SortKey | null, label: string) => (
    <div className="flex items-center">
      {key ? (
        <button
          className="inline-flex items-center gap-1 uppercase hover:text-foreground"
          onClick={() => setSort((s) => ({ key, desc: s.key === key ? !s.desc : false }))}
        >
          {label}
          {sort.key === key && (sort.desc ? <ArrowDown className="h-3 w-3" /> : <ArrowUp className="h-3 w-3" />)}
        </button>
      ) : (
        label
      )}
    </div>
  );

  return (
    <div ref={shellRef} className="rounded-xl border border-border bg-surface">
      <div
        className="sticky top-[57px] z-10 grid items-center gap-3 rounded-t-xl border-b border-border bg-muted/90 px-3 py-2.5 text-xs font-medium uppercase tracking-wide text-muted-foreground backdrop-blur-sm"
        style={{ gridTemplateColumns: grid }}
      >
        <div>
          {selectable && (
            <Checkbox
              checked={selectedVisible > 0 && selectedVisible === allIds.length}
              indeterminate={selectedVisible > 0 && selectedVisible < allIds.length}
              onChange={() => onToggle(allIds)}
              aria-label="Выбрать все найденные хосты"
              title="Выбрать все найденные"
            />
          )}
        </div>
        {header("name", "Хост")}
        {mobile ? (
          header("status", "Статус")
        ) : columns === "main" ? (
          <>
            {header("ip", "IP")}
            {header("status", "Статус")}
            {header("agent", "Агент")}
            {!compact && header(null, "ОС")}
            {header("checked", "Проверен")}
          </>
        ) : (
          <>
            {header(null, "Модель")}
            {header(null, "Процессор")}
            {header(null, "RAM")}
            {header(null, "Серийный №")}
            {!compact && header(null, "ОС")}
          </>
        )}
      </div>

      <div ref={listRef} style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
        {virtualizer.getVirtualItems().map((item) => {
          const row = rows[item.index];
          const style = {
            position: "absolute" as const,
            top: 0,
            left: 0,
            right: 0,
            height: item.size,
            transform: `translateY(${item.start - virtualizer.options.scrollMargin}px)`,
          };
          if (row.kind === "group") {
            const ids = row.hosts.map((h) => h.id);
            const count = ids.filter((id) => selected.has(id)).length;
            const online = row.hosts.filter((h) => h.status === "online").length;
            return (
              <div key={`g-${row.key}`} style={style} className="grid items-center gap-3 border-b border-border bg-muted/40 px-3 text-sm" >
                <div className="flex items-center gap-3" style={{ gridColumn: "1 / -1" }}>
                  <div className="w-[1.125rem]">
                    {selectable && (
                      <Checkbox
                        checked={count > 0 && count === ids.length}
                        indeterminate={count > 0 && count < ids.length}
                        onChange={() => onToggle(ids)}
                        aria-label={`Выбрать ${row.label}`}
                      />
                    )}
                  </div>
                  <DoorOpen className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <span className="truncate font-semibold text-foreground">{row.label}</span>
                  <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                    {pcCount(row.hosts.length)} · <span className="text-emerald-600 dark:text-emerald-400">{online} online</span>
                  </span>
                </div>
              </div>
            );
          }
          const h = row.host;
          const checked = selected.has(h.id);
          return (
            <div
              key={h.id}
              style={{ ...style, gridTemplateColumns: grid }}
              className={`grid cursor-pointer items-center gap-3 border-b border-border/60 px-3 text-sm transition-colors hover:bg-muted/50 ${checked ? "bg-blue-500/5" : ""}`}
              onClick={() => onOpen(h)}
            >
              <div onClick={(e) => e.stopPropagation()}>
                {selectable && <Checkbox checked={checked} onChange={() => onToggle([h.id])} aria-label={`Выбрать ${hostLabel(h)}`} />}
              </div>
              <div className="min-w-0">
                <div className="flex min-w-0 items-center gap-1.5">
                  <span className="truncate font-medium text-foreground">{hostLabel(h)}</span>
                  {!!alertCounts?.get(h.id) && (
                    <span className="inline-flex shrink-0 items-center gap-0.5 rounded bg-amber-500/15 px-1 text-[11px] font-medium text-amber-700 dark:text-amber-300" title="Алерты агента — подробности в карточке, вкладка «Алерты»">
                      <BellRing className="h-3 w-3" />
                      {alertCounts.get(h.id)}
                    </span>
                  )}
                </div>
                {mobile ? (
                  <div className="truncate text-xs text-subtle">
                    <span className="font-mono">{h.ip_address ?? "—"}</span>
                    {h.has_agent && <> · агент {VERSION_LABELS[versionOf(h)]}</>}
                  </div>
                ) : (
                  <>
                    {!grouped && <div className="truncate text-xs text-subtle">{tree.pathOf(h.group_id)}</div>}
                    {grouped && h.comment && <div className="truncate text-xs text-subtle">{h.comment}</div>}
                  </>
                )}
              </div>
              {mobile ? (
                <div><StatusDot status={h.status} /></div>
              ) : columns === "main" ? (
                <>
                  <div className="truncate font-mono text-xs text-foreground/80">{h.ip_address ?? "—"}</div>
                  <div><StatusDot status={h.status} /></div>
                  <div className="min-w-0"><AgentCell host={h} status={versionOf(h)} /></div>
                  {!compact && <div className="truncate text-muted-foreground">{osLabel(h.os)}</div>}
                  <div className="truncate text-muted-foreground" title={h.last_checked_at ? new Date(h.last_checked_at).toLocaleString("ru-RU") : undefined}>
                    {relativeTime(h.last_checked_at)}
                  </div>
                </>
              ) : (
                <>
                  <div className="min-w-0">
                    <div className="truncate text-foreground">{h.hw_model ?? "—"}</div>
                    <div className="truncate text-xs text-subtle">{h.hw_manufacturer}</div>
                  </div>
                  <div className="truncate text-xs text-foreground/80" title={h.hw_processor ?? ""}>{h.hw_processor ?? "—"}</div>
                  <div className="tabular-nums">{formatRam(h.hw_total_memory_bytes)}</div>
                  <div className="truncate font-mono text-xs text-muted-foreground">{h.hw_serial_number ?? "—"}</div>
                  {!compact && <div className="truncate text-xs text-muted-foreground" title={h.hw_os_caption ?? ""}>{h.hw_os_caption ?? osLabel(h.os)}</div>}
                </>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function StatusDot({ status }: { status: string }) {
  const color = status === "online" ? "bg-emerald-500" : status === "offline" ? "bg-rose-500" : "bg-slate-400";
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
      <span className={`h-2 w-2 shrink-0 rounded-full ${color}`} />
      {status === "unknown" ? "неизвестно" : status}
    </span>
  );
}

export function AgentCell({ host, status }: { host: Host; status: VersionStatus }) {
  if (!host.has_agent) return <span className="text-xs text-subtle">без агента</span>;
  const color =
    status === "outdated" ? "text-amber-600 dark:text-amber-400" : status === "up_to_date" ? "text-emerald-600 dark:text-emerald-400" : "text-muted-foreground";
  return (
    <span className="flex min-w-0 items-baseline gap-2 text-xs">
      <span className="truncate font-mono text-foreground/80">{host.agent_version ?? "—"}</span>
      <span className={`shrink-0 ${color}`}>{VERSION_LABELS[status]}</span>
    </span>
  );
}
