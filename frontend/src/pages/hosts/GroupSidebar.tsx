import { useState } from "react";
import { Building2, ChevronDown, ChevronRight, DoorOpen, Folder, Layers, Server } from "lucide-react";
import type { GroupTree, TreeNode } from "../../lib/groupTree";
import { NO_GROUP } from "../../lib/groupTree";

interface Props {
  tree: GroupTree;
  total: number;
  online: number;
  value: string;
  onChange: (groupId: string) => void;
}

/** Дерево «корпус › этаж › аудитория» как фильтр реестра: клик — показать ПК поддерева. */
export default function GroupSidebar({ tree, total, online, value, onChange }: Props) {
  const [expanded, setExpanded] = useState<Set<string>>(() => {
    // Ветка выбранной группы раскрыта сразу
    const initial = new Set<string>();
    let node = value ? tree.byId.get(value) : undefined;
    while (node?.group?.parent_id) {
      initial.add(node.group.parent_id);
      node = tree.byId.get(node.group.parent_id);
    }
    return initial;
  });

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const renderNode = (node: TreeNode) => {
    const open = expanded.has(node.id);
    const active = value === node.id;
    const Icon = node.id === NO_GROUP ? Folder : node.children.length === 0 ? DoorOpen : node.depth === 0 ? Building2 : Layers;
    return (
      <li key={node.id}>
        <div
          className={`group flex items-center gap-1 rounded-md pr-2 text-sm transition-colors ${active ? "bg-blue-600/10 text-blue-700 dark:text-blue-300" : "text-foreground hover:bg-muted"}`}
          style={{ paddingLeft: 4 + node.depth * 14 }}
        >
          {node.children.length > 0 ? (
            <button className="rounded p-0.5 text-muted-foreground hover:text-foreground" onClick={() => toggle(node.id)} aria-label={open ? "Свернуть" : "Развернуть"} aria-expanded={open}>
              {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
            </button>
          ) : (
            <span className="w-[18px]" />
          )}
          <button className="flex min-w-0 flex-1 items-center gap-1.5 py-1.5 text-left" onClick={() => onChange(active ? "" : node.id)}>
            <Icon className={`h-3.5 w-3.5 shrink-0 ${active ? "" : "text-muted-foreground"}`} />
            <span className="truncate">{node.name}</span>
            <span className="ml-auto shrink-0 pl-2 text-xs tabular-nums text-muted-foreground" title={`online ${node.online} из ${node.hostIds.length}`}>
              {node.online > 0 && <span className="text-emerald-600 dark:text-emerald-400">{node.online}</span>}
              {node.online > 0 && <span className="text-subtle">/</span>}
              {node.hostIds.length}
            </span>
          </button>
        </div>
        {open && node.children.length > 0 && <ul>{node.children.map(renderNode)}</ul>}
      </li>
    );
  };

  return (
    <nav aria-label="Группы хостов" className="text-sm">
      <button
        className={`mb-1 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left font-medium transition-colors ${!value ? "bg-blue-600/10 text-blue-700 dark:text-blue-300" : "text-foreground hover:bg-muted"}`}
        onClick={() => onChange("")}
      >
        <Server className="h-3.5 w-3.5" />
        Все хосты
        <span className="ml-auto text-xs tabular-nums text-muted-foreground">
          <span className="text-emerald-600 dark:text-emerald-400">{online}</span>
          <span className="text-subtle">/</span>
          {total}
        </span>
      </button>
      <ul>{tree.roots.map(renderNode)}</ul>
    </nav>
  );
}
