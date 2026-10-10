import type { Credential, Host } from "../api/types";
import type { GroupTree, TreeNode } from "./groupTree";

// Правила совпадают с backend (services/credential_rules.py): для SSH годится
// SSH-ключ или логин с паролем, с логином; ключ агента вручную не назначается.
export function isSshAssignable(c: Credential) {
  return !c.is_agent_managed && (c.type === "ssh_key" || c.type === "password") && !!c.login;
}

export type EffectiveCredential =
  | { source: "agent"; credentialId: string }
  | { source: "own"; credentialId: string }
  | { source: "group"; credentialId: string; groupPath: string }
  | { source: "none" };

/** Чем сервер подключится к ПК по SSH: своя учётка, иначе ближайшая учётка группы вверх по дереву. */
export function effectiveCredential(
  host: Pick<Host, "credential_id" | "group_id">,
  tree: GroupTree,
  credentials: Credential[] | undefined,
): EffectiveCredential {
  if (host.credential_id) {
    const own = credentials?.find((c) => c.id === host.credential_id);
    return own?.is_agent_managed ? { source: "agent", credentialId: host.credential_id } : { source: "own", credentialId: host.credential_id };
  }
  let node = host.group_id ? tree.byId.get(host.group_id) : undefined;
  while (node?.group) {
    if (node.group.credential_id) return { source: "group", credentialId: node.group.credential_id, groupPath: node.path };
    node = node.group.parent_id ? tree.byId.get(node.group.parent_id) : undefined;
  }
  return { source: "none" };
}

/**
 * ПК, которые подключаются учёткой этой группы: без своей учётки и без учётки
 * более близкой группы ниже по дереву. Именно их затронет смена учётки группы.
 */
export function hostsUsingGroupCredential(node: TreeNode, hostById: Map<string, Host>) {
  const result: string[] = [];
  const walk = (current: TreeNode, isRoot: boolean) => {
    if (!isRoot && current.group?.credential_id) return; // у подгруппы своя учётка
    const childIds = new Set(current.children.flatMap((c) => c.hostIds));
    for (const id of current.hostIds) {
      if (childIds.has(id)) continue;
      if (!hostById.get(id)?.credential_id) result.push(id);
    }
    current.children.forEach((child) => walk(child, false));
  };
  walk(node, true);
  return result;
}
