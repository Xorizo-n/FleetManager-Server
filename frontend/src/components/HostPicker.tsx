import { useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Building2, ChevronDown, ChevronRight, DoorOpen, Folder, Layers, Monitor } from "lucide-react";
import Checkbox from "./ui/Checkbox";
import SearchInput from "./ui/SearchInput";
import { useFleet } from "../api/queries";
import type { Host } from "../api/types";
import { compactSelection, GroupTree, NO_GROUP, TreeNode } from "../lib/groupTree";
import { hostLabel, pcCount } from "../lib/format";

type Row =
  | { kind: "group"; node: TreeNode; visibleIds: string[]; depth: number; open: boolean }
  | { kind: "host"; host: Host; depth: number };

interface HostPickerProps {
  value: Set<string>;
  onChange: (next: Set<string>) => void;
  height?: number;
}

/**
 * Выбор хостов для запуска: дерево групп с чекбоксами (весь корпус, этаж,
 * аудитория или отдельные ПК), поиск и фильтр «только online». Список
 * виртуализован — рассчитан на тысячи ПК.
 */
export default function HostPicker({ value, onChange, height = 360 }: HostPickerProps) {
  const { tree, hostById, isLoading } = useFleet();
  const [search, setSearch] = useState("");
  const [onlineOnly, setOnlineOnly] = useState(false);
  // Ветки с уже выбранными ПК раскрыты сразу (запуск из реестра хостов)
  const [expanded, setExpanded] = useState<Set<string>>(() => {
    const open = new Set<string>();
    if (value.size === 0 || value.size > 200) return open;
    const walk = (node: TreeNode) => {
      const selectedCount = node.hostIds.filter((id) => value.has(id)).length;
      if (selectedCount > 0 && selectedCount < node.hostIds.length) open.add(node.id);
      node.children.forEach(walk);
    };
    tree.roots.forEach(walk);
    return open;
  });
  const scrollRef = useRef<HTMLDivElement>(null);

  const query = search.trim().toLowerCase();
  const filtering = query !== "" || onlineOnly;

  const rows = useMemo(() => {
    const matches = (h: Host) =>
      (!onlineOnly || h.status === "online") &&
      (!query || (h.hostname ?? "").toLowerCase().includes(query) || (h.ip_address ?? "").includes(query));
    const result: Row[] = [];
    const walk = (node: TreeNode, depth: number) => {
      const visibleIds = filtering ? node.hostIds.filter((id) => matches(hostById.get(id)!)) : node.hostIds;
      // Поиск по имени группы показывает её целиком
      const groupMatches = query !== "" && node.path.toLowerCase().includes(query);
      const ids = groupMatches ? node.hostIds.filter((id) => !onlineOnly || hostById.get(id)?.status === "online") : visibleIds;
      if (ids.length === 0) return;
      // При фильтре ветки с найденными ПК раскрыты; найденная по имени группа — свёрнута
      const open = filtering ? !groupMatches || expanded.has(node.id) : expanded.has(node.id);
      result.push({ kind: "group", node, visibleIds: ids, depth, open });
      if (!open) return;
      node.children.forEach((child) => walk(child, depth + 1));
      const childIds = new Set(node.children.flatMap((c) => c.hostIds));
      const own = ids.filter((id) => !childIds.has(id)).map((id) => hostById.get(id)!).filter(Boolean);
      own.sort((a, b) => hostLabel(a).localeCompare(hostLabel(b), "ru", { numeric: true }));
      own.forEach((host) => result.push({ kind: "host", host, depth: depth + 1 }));
    };
    tree.roots.forEach((node) => walk(node, 0));
    return result;
  }, [tree, hostById, query, onlineOnly, filtering, expanded]);

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 34,
    overscan: 12,
  });

  function toggleIds(ids: string[]) {
    const next = new Set(value);
    const all = ids.every((id) => next.has(id));
    ids.forEach((id) => (all ? next.delete(id) : next.add(id)));
    onChange(next);
  }

  function toggleExpanded(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const visibleHostIds = useMemo(() => {
    if (!filtering) return [];
    return [...new Set(rows.flatMap((r) => (r.kind === "group" && r.depth === 0 ? r.visibleIds : [])))];
  }, [rows, filtering]);

  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <div className="flex flex-wrap items-center gap-2 border-b border-border bg-muted/30 p-2">
        <SearchInput value={search} onChange={setSearch} placeholder="Имя ПК, IP или группа" className="min-w-[200px] flex-1" />
        <label className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-muted-foreground hover:text-foreground">
          <Checkbox checked={onlineOnly} onChange={(e) => setOnlineOnly(e.target.checked)} />
          Только online
        </label>
        {filtering && visibleHostIds.length > 0 && (
          <button type="button" className="btn-ghost btn-sm" onClick={() => toggleIds(visibleHostIds)}>
            {visibleHostIds.every((id) => value.has(id)) ? "Снять найденные" : `Выбрать найденные (${visibleHostIds.length})`}
          </button>
        )}
      </div>

      <div ref={scrollRef} style={{ height }} className="overflow-y-auto">
        {isLoading && <p className="p-4 text-sm text-muted-foreground">Загрузка хостов…</p>}
        {!isLoading && rows.length === 0 && <p className="p-4 text-sm text-subtle">Ничего не найдено</p>}
        <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
          {virtualizer.getVirtualItems().map((item) => {
            const row = rows[item.index];
            return (
              <div
                key={row.kind === "group" ? `g-${row.node.id}` : `h-${row.host.id}`}
                style={{ position: "absolute", top: 0, left: 0, right: 0, height: item.size, transform: `translateY(${item.start}px)` }}
              >
                {row.kind === "group" ? (
                  <GroupRow
                    row={row}
                    value={value}
                    expanded={row.open}
                    onToggleExpand={() => toggleExpanded(row.node.id)}
                    onToggle={() => toggleIds(row.visibleIds)}
                  />
                ) : (
                  <HostRow host={row.host} depth={row.depth} checked={value.has(row.host.id)} onToggle={() => toggleIds([row.host.id])} />
                )}
              </div>
            );
          })}
        </div>
      </div>

      <SelectionSummary tree={tree} value={value} onClear={() => onChange(new Set())} />
    </div>
  );
}

function GroupRow({ row, value, expanded, onToggleExpand, onToggle }: {
  row: Extract<Row, { kind: "group" }>;
  value: Set<string>;
  expanded: boolean;
  onToggleExpand: () => void;
  onToggle: () => void;
}) {
  const { node, visibleIds, depth } = row;
  const selected = visibleIds.filter((id) => value.has(id)).length;
  const Icon = node.id === NO_GROUP ? Folder : node.children.length === 0 ? DoorOpen : depth === 0 ? Building2 : Layers;
  return (
    <div className="flex h-full items-center gap-2 border-b border-border/50 pr-3 text-sm hover:bg-muted/40" style={{ paddingLeft: 8 + depth * 20 }}>
      <button type="button" onClick={onToggleExpand} className="rounded p-0.5 text-muted-foreground hover:text-foreground" aria-label={expanded ? "Свернуть" : "Развернуть"}>
        {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
      </button>
      <Checkbox
        checked={selected > 0 && selected === visibleIds.length}
        indeterminate={selected > 0 && selected < visibleIds.length}
        onChange={onToggle}
        aria-label={`Выбрать ${node.path}`}
      />
      <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
      <button type="button" onClick={onToggleExpand} className="min-w-0 truncate text-left font-medium text-foreground">
        {node.name}
      </button>
      <span className="ml-auto shrink-0 text-xs tabular-nums text-muted-foreground">
        {selected > 0 && <span className="mr-2 text-blue-600 dark:text-blue-400">{selected} выбрано</span>}
        {pcCount(visibleIds.length)}
      </span>
    </div>
  );
}

function HostRow({ host, depth, checked, onToggle }: { host: Host; depth: number; checked: boolean; onToggle: () => void }) {
  const dot = host.status === "online" ? "bg-emerald-500" : host.status === "offline" ? "bg-rose-500" : "bg-slate-400";
  return (
    <label className="flex h-full cursor-pointer items-center gap-2 border-b border-border/30 pr-3 text-sm hover:bg-muted/40" style={{ paddingLeft: 8 + depth * 20 + 24 }}>
      <Checkbox checked={checked} onChange={onToggle} />
      <Monitor className="h-3.5 w-3.5 shrink-0 text-subtle" />
      <span className="truncate text-foreground">{hostLabel(host)}</span>
      <span className="font-mono text-xs text-subtle">{host.ip_address}</span>
      <span className="ml-auto flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
        <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
        {host.status}
      </span>
    </label>
  );
}

/** «Выбрано 23 ПК: MR32 › 4 этаж › 411, SU5 › 2 этаж + 2 ПК» */
export function SelectionSummary({ tree, value, onClear }: { tree: GroupTree; value: Set<string>; onClear?: () => void }) {
  const { groupIds, hostIds } = useMemo(() => compactSelection(tree, value), [tree, value]);
  if (value.size === 0) {
    return <div className="border-t border-border bg-muted/30 px-3 py-2 text-sm text-subtle">Хосты не выбраны</div>;
  }
  const parts = groupIds.slice(0, 4).map((id) => tree.pathOf(id));
  const more = groupIds.length - parts.length;
  return (
    <div className="flex items-start gap-3 border-t border-border bg-blue-500/5 px-3 py-2 text-sm">
      <p className="min-w-0 flex-1 text-foreground">
        <b className="tabular-nums">Выбрано {pcCount(value.size)}</b>
        {groupIds.length > 0 && (
          <span className="text-muted-foreground">
            : {parts.join(", ")}
            {more > 0 && ` и ещё ${more} групп`}
            {hostIds.length > 0 && ` + ${pcCount(hostIds.length)}`}
          </span>
        )}
      </p>
      {onClear && (
        <button type="button" className="shrink-0 text-xs text-muted-foreground hover:text-foreground" onClick={onClear}>
          Очистить
        </button>
      )}
    </div>
  );
}
