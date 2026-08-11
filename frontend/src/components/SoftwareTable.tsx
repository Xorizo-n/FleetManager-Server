import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import Badge from "./ui/Badge";

export interface SoftwareItemRow {
  id: string;
  host_id: string;
  name: string;
  version: string | null;
  install_method: string;
  status: string;
  detected_at: string;
}

interface HostRow {
  id: string;
  hostname: string | null;
  ip_address: string | null;
  group_id: string | null;
}

interface HostGroupRow {
  id: string;
  name: string;
}

interface SoftwareTableProps {
  items: SoftwareItemRow[];
  hosts: HostRow[];
  groups: HostGroupRow[];
}

export default function SoftwareTable({ items, hosts, groups }: SoftwareTableProps) {
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({});
  const [collapsedHosts, setCollapsedHosts] = useState<Record<string, boolean>>({});

  const itemsByHost = useMemo(() => {
    const result = new Map<string, SoftwareItemRow[]>();
    for (const item of items) {
      const hostItems = result.get(item.host_id) || [];
      hostItems.push(item);
      result.set(item.host_id, hostItems);
    }
    return result;
  }, [items]);

  const groupedHosts = useMemo(() => {
    const groupsById = new Map(groups.map((group) => [group.id, group]));
    const grouped = new Map<string, { id: string; name: string; hosts: HostRow[] }>();
    for (const host of hosts) {
      const group = host.group_id ? groupsById.get(host.group_id) : undefined;
      const key = group?.id || "ungrouped";
      const entry = grouped.get(key) || { id: key, name: group?.name || "Без группы", hosts: [] };
      entry.hosts.push(host);
      grouped.set(key, entry);
    }
    return Array.from(grouped.values())
      .map((group) => ({ ...group, hosts: group.hosts.filter((host) => (itemsByHost.get(host.id) || []).length > 0) }))
      .filter((group) => group.hosts.length > 0)
      .sort((left, right) => left.name.localeCompare(right.name, "ru"));
  }, [groups, hosts, itemsByHost]);

  function hostLabel(host: HostRow) {
    return host.hostname || host.ip_address || host.id;
  }

  if (groupedHosts.length === 0) {
    return <div className="surface-panel px-3 py-8 text-center text-subtle">Нет данных</div>;
  }

  return (
    <div className="space-y-3">
      {groupedHosts.map((group) => {
        const groupCollapsed = collapsedGroups[group.id] === true;
        return (
          <section key={group.id} className="surface-panel p-0">
            <button
              className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left text-sm font-semibold text-foreground hover:bg-muted/40"
              onClick={() => setCollapsedGroups((prev) => ({ ...prev, [group.id]: !groupCollapsed }))}
              aria-expanded={!groupCollapsed}
            >
              <span className="flex items-center gap-2">
                {groupCollapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                {group.name}
              </span>
              <span className="text-xs font-normal text-muted-foreground">{group.hosts.length} хостов</span>
            </button>

            {!groupCollapsed && (
              <div className="space-y-2 border-t border-border p-3">
                {group.hosts.map((host) => {
                  const hostItems = itemsByHost.get(host.id) || [];
                  const hostCollapsed = collapsedHosts[host.id] === true;
                  return (
                    <div key={host.id} className="overflow-hidden rounded-lg border border-border/70">
                      <button
                        className="flex w-full items-center justify-between gap-3 bg-muted/30 px-3 py-2 text-left text-sm font-medium text-foreground hover:bg-muted/60"
                        onClick={() => setCollapsedHosts((prev) => ({ ...prev, [host.id]: !hostCollapsed }))}
                        aria-expanded={!hostCollapsed}
                      >
                        <span className="flex items-center gap-2">
                          {hostCollapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                          {hostLabel(host)}
                        </span>
                        <span className="text-xs font-normal text-muted-foreground">{hostItems.length} пакетов</span>
                      </button>

                      {!hostCollapsed && (
                        <div className="overflow-x-auto">
                          <table className="table-base">
                            <thead>
                              <tr>
                                <th>Название</th>
                                <th>Версия</th>
                                <th>Способ установки</th>
                                <th>Статус</th>
                                <th>Обнаружено</th>
                              </tr>
                            </thead>
                            <tbody>
                              {hostItems.map((item) => (
                                <tr key={item.id}>
                                  <td className="font-medium text-foreground">{item.name}</td>
                                  <td className="font-mono text-foreground/80">{item.version || "—"}</td>
                                  <td>{item.install_method}</td>
                                  <td><Badge status={item.status} /></td>
                                  <td className="text-muted-foreground">{new Date(item.detected_at).toLocaleString("ru-RU")}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
