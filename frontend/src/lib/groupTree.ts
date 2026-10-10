import type { Host, HostGroup } from "../api/types";

// Дерево групп «корпус > этаж > аудитория» и всё, что из него выводится: пути
// для подписей, поддеревья для фильтров и выбора, счётчики ПК.

export const NO_GROUP = "__none__";
export const NO_GROUP_LABEL = "Без группы";

export interface TreeNode {
  id: string;
  group: HostGroup | null; // null — псевдогруппа «Без группы»
  name: string; // короткое имя: «D206» внутри корпуса SU5
  path: string; // «SU5 › 2 этаж › D206»
  depth: number;
  children: TreeNode[];
  hostIds: string[]; // все ПК поддерева
  online: number;
}

export interface GroupTree {
  roots: TreeNode[];
  byId: Map<string, TreeNode>;
  /** Группа и все её подгруппы */
  descendants: (groupId: string) => Set<string>;
  /** Путь группы для подписи; для хоста без группы — «Без группы» */
  pathOf: (groupId: string | null) => string;
  /** Отсортированные варианты для <select> */
  options: { id: string; label: string; depth: number }[];
}

const collator = new Intl.Collator("ru", { numeric: true });

export function buildGroupTree(groups: HostGroup[], hosts: Host[]): GroupTree {
  const known = new Map(groups.map((g) => [g.id, g]));
  const childrenOf = new Map<string | null, HostGroup[]>();
  for (const g of groups) {
    const parent = g.parent_id && known.has(g.parent_id) ? g.parent_id : null;
    if (!childrenOf.has(parent)) childrenOf.set(parent, []);
    childrenOf.get(parent)!.push(g);
  }
  const hostsByGroup = new Map<string, Host[]>();
  for (const h of hosts) {
    const key = h.group_id && known.has(h.group_id) ? h.group_id : NO_GROUP;
    if (!hostsByGroup.has(key)) hostsByGroup.set(key, []);
    hostsByGroup.get(key)!.push(h);
  }

  const byId = new Map<string, TreeNode>();
  const seen = new Set<string>();

  function build(group: HostGroup, depth: number, rootName: string | null, parentPath: string): TreeNode | null {
    if (seen.has(group.id)) return null; // цикл в данных
    seen.add(group.id);
    // «SU5-D206» внутри корпуса SU5 показывается как «D206»: корпус и так виден в пути
    const prefix = rootName ? `${rootName}-` : "";
    const name =
      prefix && group.name.length > prefix.length && group.name.toUpperCase().startsWith(prefix.toUpperCase())
        ? group.name.slice(prefix.length)
        : group.name;
    const path = parentPath ? `${parentPath} › ${name}` : name;
    const node: TreeNode = { id: group.id, group, name, path, depth, children: [], hostIds: [], online: 0 };
    byId.set(group.id, node);
    const own = hostsByGroup.get(group.id) ?? [];
    node.hostIds = own.map((h) => h.id);
    node.online = own.filter((h) => h.status === "online").length;
    for (const child of [...(childrenOf.get(group.id) ?? [])].sort((a, b) => collator.compare(a.name, b.name))) {
      const childNode = build(child, depth + 1, rootName ?? group.name, path);
      if (!childNode) continue;
      node.children.push(childNode);
      node.hostIds.push(...childNode.hostIds);
      node.online += childNode.online;
    }
    return node;
  }

  const roots = [...(childrenOf.get(null) ?? [])]
    .sort((a, b) => collator.compare(a.name, b.name))
    .map((g) => build(g, 0, null, ""))
    .filter((n): n is TreeNode => n !== null);

  const ungrouped = hostsByGroup.get(NO_GROUP) ?? [];
  if (ungrouped.length > 0) {
    const node: TreeNode = {
      id: NO_GROUP,
      group: null,
      name: NO_GROUP_LABEL,
      path: NO_GROUP_LABEL,
      depth: 0,
      children: [],
      hostIds: ungrouped.map((h) => h.id),
      online: ungrouped.filter((h) => h.status === "online").length,
    };
    roots.push(node);
    byId.set(NO_GROUP, node);
  }

  const descendantCache = new Map<string, Set<string>>();
  function descendants(groupId: string) {
    if (descendantCache.has(groupId)) return descendantCache.get(groupId)!;
    const result = new Set<string>();
    const walk = (node: TreeNode | undefined) => {
      if (!node || result.has(node.id)) return;
      result.add(node.id);
      node.children.forEach(walk);
    };
    walk(byId.get(groupId));
    descendantCache.set(groupId, result);
    return result;
  }

  const options: GroupTree["options"] = [];
  const walk = (node: TreeNode) => {
    if (node.group) options.push({ id: node.id, label: node.path, depth: node.depth });
    node.children.forEach(walk);
  };
  roots.forEach(walk);

  return {
    roots,
    byId,
    descendants,
    pathOf: (groupId) => (groupId ? byId.get(groupId)?.path ?? "—" : NO_GROUP_LABEL),
    options,
  };
}

/**
 * Сжимает набор ПК до целиком выбранных групп + отдельных ПК: «MR32-411 целиком
 * + 2 ПК». Берутся самые верхние группы, все ПК которых выбраны.
 */
export function compactSelection(tree: GroupTree, selected: Set<string>) {
  const groupIds: string[] = [];
  const covered = new Set<string>();
  const walk = (node: TreeNode) => {
    if (node.group && node.hostIds.length > 0 && node.hostIds.every((id) => selected.has(id))) {
      groupIds.push(node.id);
      node.hostIds.forEach((id) => covered.add(id));
      return;
    }
    node.children.forEach(walk);
  };
  tree.roots.forEach(walk);
  return { groupIds, hostIds: [...selected].filter((id) => !covered.has(id)) };
}
