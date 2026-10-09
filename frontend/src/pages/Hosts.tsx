import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  ArrowUpCircle,
  Building2,
  CheckSquare,
  ChevronDown,
  ChevronRight,
  ChevronsDownUp,
  ChevronsUpDown,
  DoorOpen,
  Download,
  Filter,
  FolderPlus,
  Layers,
  Plus,
  RefreshCw,
  Square,
  Trash2,
  Upload,
  X,
  XCircle,
} from "lucide-react";
import { apiClient, getAccessToken } from "../api/client";
import { useAuth } from "../context/AuthContext";
import Badge from "../components/ui/Badge";
import Button from "../components/ui/Button";
import TaskLog from "../components/TaskLog";

interface HostGroup {
  id: string;
  name: string;
  description: string | null;
  // Корпус > этаж > аудитория: сервер раскладывает ПК по имени (SU5-D206-TEMP -> SU5-D206).
  parent_id: string | null;
  is_auto: boolean;
}

interface Host {
  id: string;
  ip_address: string | null;
  hostname: string | null;
  group_id: string | null;
  os: string;
  status: string;
  last_checked_at: string | null;
  comment: string | null;
  has_agent: boolean;
  agent_version: string | null;
  agent_version_checked_at: string | null;
}

interface Credential {
  id: string;
  name: string;
}

interface DiagnosticTask {
  id: string;
  task_type: string;
  host_ids: string[];
  status: string;
  log_output: string | null;
}

interface AgentHostVersion {
  host_id: string;
  agent_version: string | null;
  version_status: string;
  agent_version_checked_at: string | null;
}

interface AgentVersionOverview {
  available_version: string | null;
  installer_present: boolean;
  total_agents: number;
  up_to_date: number;
  outdated: number;
  unknown: number;
  hosts: AgentHostVersion[];
}

const OS_OPTIONS = ["windows_10", "windows_11", "windows_server"];
const STATUS_OPTIONS = ["online", "offline", "unknown"];
const NO_GROUP = "__none__";
const NO_GROUP_TARGET = "__none__";
const NO_GROUP_LABEL = "Без группы";

const OS_LABELS: Record<string, string> = {
  windows_10: "Windows 10",
  windows_11: "Windows 11",
  windows_server: "Windows Server",
};

function osLabel(os: string) {
  return OS_LABELS[os] ?? os;
}

const AGENT_FILTER_OPTIONS: { value: string; label: string }[] = [
  { value: "with", label: "С агентом" },
  { value: "without", label: "Без агента" },
  { value: "up_to_date", label: "Актуальна" },
  { value: "outdated", label: "Устарела" },
  { value: "newer", label: "Новее сервера" },
  { value: "unknown", label: "Версия неизвестна" },
];

const CHECKED_FILTER_OPTIONS: { value: string; label: string }[] = [
  { value: "never", label: "Никогда" },
  { value: "24h", label: "За 24 часа" },
  { value: "7d", label: "За 7 дней" },
  { value: "older", label: "Старше 7 дней" },
];

interface HostFilters {
  hostname: string;
  ip: string;
  group: string;
  os: string;
  status: string;
  agent: string;
  checked: string;
}

const EMPTY_FILTERS: HostFilters = { hostname: "", ip: "", group: "", os: "", status: "", agent: "", checked: "" };

const VERSION_LABEL: Record<string, string> = {
  up_to_date: "актуальна",
  outdated: "устарела",
  newer: "новее сервера",
  unknown: "неизвестна",
  no_agent: "нет агента",
};

const VERSION_TONE: Record<string, "success" | "warning" | "info" | "neutral"> = {
  up_to_date: "success",
  outdated: "warning",
  newer: "info",
  unknown: "neutral",
  no_agent: "neutral",
};

function relativeTime(iso: string | null): string {
  if (!iso) return "никогда";
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 0) return "только что";
  const min = Math.floor(ms / 60000);
  if (min < 1) return "только что";
  if (min < 60) return `${min} мин назад`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} ч назад`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day} дн назад`;
  return new Date(iso).toLocaleDateString();
}

// Узел дерева групп на странице: корпус > этаж > аудитория.
interface GroupNode {
  key: string;
  name: string;
  // ПК, лежащие прямо в этой группе (обычно только у аудитории)
  hosts: Host[];
  children: GroupNode[];
  // Все ПК поддерева — для сводки, выбора и сворачивания целого корпуса или этажа
  allHosts: Host[];
}

export default function Hosts() {
  const { user } = useAuth();
  const canEdit = user?.role === "admin" || user?.role === "operator";

  const [hosts, setHosts] = useState<Host[]>([]);
  const [groups, setGroups] = useState<HostGroup[]>([]);
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [filters, setFilters] = useState<HostFilters>(EMPTY_FILTERS);
  const [showFilters, setShowFilters] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [importResult, setImportResult] = useState<string | null>(null);
  const [hostFormError, setHostFormError] = useState<string | null>(null);
  const [diagnosticHost, setDiagnosticHost] = useState<Host | null>(null);
  const [diagnosticTask, setDiagnosticTask] = useState<DiagnosticTask | null>(null);
  const [diagnosticError, setDiagnosticError] = useState<string | null>(null);
  const [diagnosticStarting, setDiagnosticStarting] = useState(false);
  const [selectedHostIds, setSelectedHostIds] = useState<string[]>([]);
  const [showGroupPanel, setShowGroupPanel] = useState(false);
  const [groupTarget, setGroupTarget] = useState("");
  const [newGroupName, setNewGroupName] = useState("");
  const [groupError, setGroupError] = useState<string | null>(null);
  const [groupSaving, setGroupSaving] = useState(false);
  const [agentVersions, setAgentVersions] = useState<AgentVersionOverview | null>(null);
  const [agentTask, setAgentTask] = useState<DiagnosticTask | null>(null);
  const [agentTaskTitle, setAgentTaskTitle] = useState("");
  const [agentError, setAgentError] = useState<string | null>(null);
  const [agentBusy, setAgentBusy] = useState<"scan" | "update" | null>(null);
  // По умолчанию всё дерево групп свёрнуто: хранятся только развёрнутые
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [form, setForm] = useState({
    ip_address: "",
    hostname: "",
    os: OS_OPTIONS[0],
    group_id: "",
    comment: "",
    credential_id: "",
  });

  async function loadHosts() {
    const { data } = await apiClient.get<Host[]>("/hosts");
    setHosts(data);
  }

  async function loadGroups() {
    const { data } = await apiClient.get<HostGroup[]>("/hosts/groups");
    setGroups(data);
  }

  async function loadCredentials() {
    try {
      const { data } = await apiClient.get<Credential[]>("/credentials");
      setCredentials(data);
    } catch {
      setCredentials([]);
    }
  }

  async function loadAgentVersions() {
    try {
      const { data } = await apiClient.get<AgentVersionOverview>("/agent/versions");
      setAgentVersions(data);
    } catch {
      setAgentVersions(null);
    }
  }

  useEffect(() => {
    loadHosts();
    loadGroups();
    loadCredentials();
    loadAgentVersions();
  }, []);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    const hostname = form.hostname.trim();
    const ipAddress = form.ip_address.trim();
    if (!hostname && !ipAddress) {
      setHostFormError("Укажите имя хоста или IP-адрес");
      return;
    }
    setHostFormError(null);
    try {
      await apiClient.post("/hosts", {
        ip_address: ipAddress || null,
        hostname: hostname || null,
        os: form.os,
        group_id: form.group_id || null,
        comment: form.comment || null,
        credential_id: form.credential_id || null,
      });
      setForm({ ip_address: "", hostname: "", os: OS_OPTIONS[0], group_id: "", comment: "", credential_id: "" });
      setShowForm(false);
      loadHosts();
    } catch (err: any) {
      setHostFormError(err.response?.data?.detail || "Не удалось добавить хост");
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Удалить хост?")) return;
    await apiClient.delete(`/hosts/${id}`);
    loadHosts();
  }

  function toggleHostSelection(id: string) {
    setSelectedHostIds((prev) => (prev.includes(id) ? prev.filter((hostId) => hostId !== id) : [...prev, id]));
  }

  function toggleAllVisibleHosts() {
    const visibleIds = filteredHosts.map((host) => host.id);
    const allSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedHostIds.includes(id));
    setSelectedHostIds(allSelected ? [] : visibleIds);
  }

  function toggleGroupSelection(sectionHosts: Host[]) {
    const ids = sectionHosts.map((h) => h.id);
    const allSelected = ids.length > 0 && ids.every((id) => selectedHostIds.includes(id));
    setSelectedHostIds((prev) => {
      if (allSelected) return prev.filter((id) => !ids.includes(id));
      const merged = new Set(prev);
      ids.forEach((id) => merged.add(id));
      return [...merged];
    });
  }

  function toggleGroupCollapsed(key: string) {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function assignSelectedHosts() {
    if (selectedHostIds.length === 0) return;
    const groupName = newGroupName.trim();
    if (groupTarget !== NO_GROUP_TARGET && !groupTarget && !groupName) {
      setGroupError("Выберите существующую группу, «Без группы» или укажите имя новой");
      return;
    }
    setGroupError(null);
    setGroupSaving(true);
    try {
      if (groupTarget === NO_GROUP_TARGET) {
        await apiClient.post("/hosts/groups/unassign", { host_ids: selectedHostIds });
      } else {
        await apiClient.post("/hosts/groups/assign", {
          host_ids: selectedHostIds,
          ...(groupTarget ? { group_id: groupTarget } : { group_name: groupName }),
        });
      }
      await Promise.all([loadGroups(), loadHosts()]);
      setSelectedHostIds([]);
      setShowGroupPanel(false);
      setGroupTarget("");
      setNewGroupName("");
    } catch (err: any) {
      setGroupError(err.response?.data?.detail || "Не удалось изменить группу хостов");
    } finally {
      setGroupSaving(false);
    }
  }

  async function startDiagnostic(host: Host) {
    setDiagnosticHost(host);
    setDiagnosticTask(null);
    setDiagnosticError(null);
    setDiagnosticStarting(true);
    try {
      const { data } = await apiClient.post(`/hosts/${host.id}/diagnostics`);
      setDiagnosticTask({ ...data, log_output: null });
    } catch (err: any) {
      setDiagnosticError(err.response?.data?.detail || "Не удалось запустить диагностику");
    } finally {
      setDiagnosticStarting(false);
    }
  }

  useEffect(() => {
    if (!diagnosticTask || !["queued", "running"].includes(diagnosticTask.status)) return;
    const interval = setInterval(async () => {
      try {
        const { data } = await apiClient.get<DiagnosticTask>(`/tasks/${diagnosticTask.id}`);
        setDiagnosticTask(data);
      } catch {
        // The stream remains the source of live output; polling is best effort.
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [diagnosticTask?.id, diagnosticTask?.status]);

  async function startAgentTask(kind: "scan" | "update", hostIds: string[], title: string) {
    setAgentBusy(kind);
    setAgentError(null);
    setAgentTask(null);
    setAgentTaskTitle(title);
    try {
      const { data } = await apiClient.post(kind === "scan" ? "/agent/version-scan" : "/agent/update", {
        host_ids: hostIds,
      });
      setAgentTask({ ...data, log_output: null });
    } catch (err: any) {
      setAgentError(err.response?.data?.detail || "Не удалось запустить операцию с агентом");
    } finally {
      setAgentBusy(null);
    }
  }

  // Пустой список host_ids на сервере означает «все хосты с агентом».
  function selectedAgentHostIds() {
    return selectedHostIds.filter((id) => hosts.find((host) => host.id === id)?.has_agent);
  }

  useEffect(() => {
    if (!agentTask || !["queued", "running"].includes(agentTask.status)) return;
    const interval = setInterval(async () => {
      try {
        const { data } = await apiClient.get<DiagnosticTask>(`/tasks/${agentTask.id}`);
        setAgentTask(data);
        if (!["queued", "running"].includes(data.status)) {
          await Promise.all([loadHosts(), loadAgentVersions()]);
        }
      } catch {
        // Живой лог идёт через SSE; опрос статуса — best effort.
      }
    }, 2000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentTask?.id, agentTask?.status]);

  function agentVersionOf(hostId: string): AgentHostVersion | undefined {
    return agentVersions?.hosts.find((entry) => entry.host_id === hostId);
  }

  function agentStateOf(host: Host): string {
    if (!host.has_agent) return "no_agent";
    return agentVersionOf(host.id)?.version_status ?? "unknown";
  }

  const groupTree = useMemo(() => {
    const byId = new Map(groups.map((g) => [g.id, g]));
    const childrenOf = new Map<string, string[]>();
    for (const g of groups) {
      if (g.parent_id && byId.has(g.parent_id)) {
        if (!childrenOf.has(g.parent_id)) childrenOf.set(g.parent_id, []);
        childrenOf.get(g.parent_id)!.push(g.id);
      }
    }
    // Цепочка от корня до группы; на цикле в данных просто останавливается
    const chain = (id: string): HostGroup[] => {
      const result: HostGroup[] = [];
      const seen = new Set<string>();
      let current = byId.get(id);
      while (current && !seen.has(current.id)) {
        seen.add(current.id);
        result.unshift(current);
        current = current.parent_id ? byId.get(current.parent_id) : undefined;
      }
      return result;
    };
    // «SU5-D206» внутри корпуса SU5 показывается как «D206»: корпус и так виден
    // в пути. В базе и inventory Ansible имя остаётся полным — оно уникально.
    const shortNames = new Map<string, string>();
    for (const g of groups) {
      const root = chain(g.id)[0];
      const prefix = root && root.id !== g.id ? `${root.name}-` : "";
      shortNames.set(
        g.id,
        prefix && g.name.length > prefix.length && g.name.toUpperCase().startsWith(prefix.toUpperCase())
          ? g.name.slice(prefix.length)
          : g.name,
      );
    }
    const options = groups
      .map((g) => {
        const path = chain(g.id).map((item) => shortNames.get(item.id) ?? item.name);
        return { id: g.id, name: g.name, label: path.join(" › ") };
      })
      .sort((a, b) => a.label.localeCompare(b.label, "ru", { numeric: true }));
    const descendants = (id: string): Set<string> => {
      const result = new Set<string>();
      const stack = [id];
      while (stack.length > 0) {
        const current = stack.pop()!;
        if (result.has(current)) continue;
        result.add(current);
        stack.push(...(childrenOf.get(current) ?? []));
      }
      return result;
    };
    return { options, descendants, shortNames };
  }, [groups]);

  const filteredHosts = useMemo(() => {
    const hostname = filters.hostname.trim().toLowerCase();
    const ip = filters.ip.trim().toLowerCase();
    const now = Date.now();

    return hosts.filter((h) => {
      if (hostname && !(h.hostname || "").toLowerCase().includes(hostname)) return false;
      if (ip && !(h.ip_address || "").toLowerCase().includes(ip)) return false;
      if (filters.group) {
        if (filters.group === NO_GROUP) {
          if (h.group_id !== null) return false;
        } else if (h.group_id === null || !groupTree.descendants(filters.group).has(h.group_id)) {
          return false;
        }
      }
      if (filters.os && h.os !== filters.os) return false;
      if (filters.status && h.status !== filters.status) return false;
      if (filters.agent) {
        if (filters.agent === "with" && !h.has_agent) return false;
        else if (filters.agent === "without" && h.has_agent) return false;
        else if (!["with", "without"].includes(filters.agent) && agentStateOf(h) !== filters.agent) return false;
      }
      if (filters.checked) {
        const checkedAt = h.last_checked_at ? new Date(h.last_checked_at).getTime() : null;
        const ageMs = checkedAt !== null ? now - checkedAt : null;
        if (filters.checked === "never" && checkedAt !== null) return false;
        if (filters.checked === "24h" && (ageMs === null || ageMs > 24 * 3600 * 1000)) return false;
        if (filters.checked === "7d" && (ageMs === null || ageMs > 7 * 24 * 3600 * 1000)) return false;
        if (filters.checked === "older" && (ageMs === null || ageMs <= 7 * 24 * 3600 * 1000)) return false;
      }
      return true;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hosts, filters, agentVersions, groupTree]);

  // Видимый (уже отфильтрованный) список раскладывается деревом групп:
  // корпус > этаж > аудитория. Ветки без ПК после фильтров не показываются.
  const groupNodes = useMemo<GroupNode[]>(() => {
    const byGroup = new Map<string, Host[]>();
    for (const h of filteredHosts) {
      const key = h.group_id ?? NO_GROUP;
      if (!byGroup.has(key)) byGroup.set(key, []);
      byGroup.get(key)!.push(h);
    }
    const sortByName = (a: Host, b: Host) => (a.hostname || a.ip_address || "").localeCompare(b.hostname || b.ip_address || "", "ru");
    const byName = (a: { name: string }, b: { name: string }) => a.name.localeCompare(b.name, "ru", { numeric: true });

    const known = new Set(groups.map((g) => g.id));
    const childGroups = new Map<string, HostGroup[]>();
    const roots: HostGroup[] = [];
    for (const g of groups) {
      if (g.parent_id && known.has(g.parent_id)) {
        if (!childGroups.has(g.parent_id)) childGroups.set(g.parent_id, []);
        childGroups.get(g.parent_id)!.push(g);
      } else {
        roots.push(g);
      }
    }

    const build = (group: HostGroup, seen: Set<string>): GroupNode | null => {
      if (seen.has(group.id)) return null; // цикл в данных
      seen.add(group.id);
      const children = (childGroups.get(group.id) ?? [])
        .sort(byName)
        .map((child) => build(child, seen))
        .filter((node): node is GroupNode => node !== null);
      const hosts = [...(byGroup.get(group.id) ?? [])].sort(sortByName);
      const allHosts = [...hosts, ...children.flatMap((child) => child.allHosts)];
      const name = groupTree.shortNames.get(group.id) ?? group.name;
      return allHosts.length > 0 ? { key: group.id, name, hosts, children, allHosts } : null;
    };

    const seen = new Set<string>();
    const result = roots
      .sort(byName)
      .map((g) => build(g, seen))
      .filter((node): node is GroupNode => node !== null);
    const ungrouped = [...(byGroup.get(NO_GROUP) ?? [])].sort(sortByName);
    if (ungrouped.length > 0) {
      result.push({ key: NO_GROUP, name: NO_GROUP_LABEL, hosts: ungrouped, children: [], allHosts: ungrouped });
    }
    return result;
  }, [filteredHosts, groups, groupTree]);

  const groupKeys = useMemo(() => {
    const keys: string[] = [];
    const walk = (node: GroupNode) => {
      keys.push(node.key);
      node.children.forEach(walk);
    };
    groupNodes.forEach(walk);
    return keys;
  }, [groupNodes]);
  const anyGroupExpanded = groupKeys.some((key) => expandedGroups.has(key));

  function toggleAllGroups() {
    setExpandedGroups(anyGroupExpanded ? new Set() : new Set(groupKeys));
  }

  const overallStats = useMemo(() => {
    let online = 0;
    let offline = 0;
    let withAgent = 0;
    for (const h of hosts) {
      if (h.status === "online") online += 1;
      else if (h.status === "offline") offline += 1;
      if (h.has_agent) withAgent += 1;
    }
    return { total: hosts.length, online, offline, withAgent };
  }, [hosts]);

  const activeFilterCount = Object.values(filters).filter((v) => v !== "").length;
  const filtersActive = activeFilterCount > 0;

  // С фильтрами найденные ПК должны быть видны сразу — дерево раскрывается;
  // без фильтров возвращается к виду по умолчанию (всё свёрнуто).
  useEffect(() => {
    setExpandedGroups(filtersActive ? new Set(groupKeys) : new Set());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters]);

  function updateFilter<K extends keyof HostFilters>(key: K, value: string) {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }

  async function handleImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const formData = new FormData();
    formData.append("file", file);
    const { data } = await apiClient.post("/hosts/import-csv", formData);
    setImportResult(`Создано: ${data.created}, пропущено: ${data.skipped}${data.errors.length ? `, ошибки: ${data.errors.length}` : ""}`);
    loadHosts();
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function downloadInventory() {
    const token = getAccessToken();
    fetch(`${apiClient.defaults.baseURL}/hosts/inventory`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((r) => r.text())
      .then((text) => {
        const blob = new Blob([text], { type: "text/plain" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "inventory.ini";
        a.click();
        URL.revokeObjectURL(url);
      });
  }

  const visibleCount = filteredHosts.length;
  const allVisibleSelected = visibleCount > 0 && filteredHosts.every((h) => selectedHostIds.includes(h.id));

  function renderHostTable(tableHosts: Host[], groupName: string) {
    return (
      <table className="table-base">
        <thead>
          <tr>
            {canEdit && (
              <th className="w-10">
                <input
                  type="checkbox"
                  checked={tableHosts.length > 0 && tableHosts.every((h) => selectedHostIds.includes(h.id))}
                  onChange={() => toggleGroupSelection(tableHosts)}
                  aria-label={`Выбрать все хосты в группе ${groupName}`}
                />
              </th>
            )}
            <th>Hostname</th>
            <th>IP</th>
            <th>OS</th>
            <th>Статус</th>
            <th>Агент</th>
            <th>Проверен</th>
            {canEdit && <th className="text-right">Действия</th>}
          </tr>
        </thead>
        <tbody>
          {tableHosts.map((h) => (
            <tr key={h.id}>
              {canEdit && (
                <td className="w-10">
                  <input
                    type="checkbox"
                    checked={selectedHostIds.includes(h.id)}
                    onChange={() => toggleHostSelection(h.id)}
                    aria-label={`Выбрать ${h.hostname || h.ip_address || h.id}`}
                  />
                </td>
              )}
              <td className="font-medium text-foreground">{h.hostname || "—"}</td>
              <td className="font-mono text-foreground/80">{h.ip_address || "—"}</td>
              <td className="text-muted-foreground">{osLabel(h.os)}</td>
              <td><Badge status={h.status} /></td>
              <td>
                {h.has_agent ? (
                  <div className="flex flex-col gap-1">
                    <span className="font-mono text-xs text-foreground/80">
                      {agentVersionOf(h.id)?.agent_version ?? h.agent_version ?? "—"}
                    </span>
                    <Badge
                      status={agentVersionOf(h.id)?.version_status ?? "unknown"}
                      tone={VERSION_TONE[agentVersionOf(h.id)?.version_status ?? "unknown"]}
                    >
                      {VERSION_LABEL[agentVersionOf(h.id)?.version_status ?? "unknown"]}
                    </Badge>
                  </div>
                ) : (
                  <span className="text-subtle">без агента</span>
                )}
              </td>
              <td className="text-muted-foreground" title={h.last_checked_at ? new Date(h.last_checked_at).toLocaleString() : undefined}>
                {relativeTime(h.last_checked_at)}
              </td>
              {canEdit && (
                <td className="text-right">
                  <div className="inline-flex items-center gap-1">
                    <button
                      onClick={() => startDiagnostic(h)}
                      disabled={diagnosticStarting && diagnosticHost?.id === h.id}
                      className="action-icon"
                      title="Запустить диагностику подключения"
                      aria-label={`Диагностика ${h.hostname || h.ip_address}`}
                    >
                      <Activity className="h-3.5 w-3.5" />
                    </button>
                    <button
                      onClick={() => handleDelete(h.id)}
                      className="action-danger"
                      title="Удалить хост"
                      aria-label={`Удалить ${h.hostname || h.ip_address}`}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    );
  }

  // Заголовок группы любого уровня: сворачивание, сводка online/offline и
  // выбор всех ПК поддерева (весь корпус, весь этаж или одна аудитория).
  function renderGroupHeader(node: GroupNode, level: "building" | "floor" | "room") {
    const collapsed = !expandedGroups.has(node.key);
    const online = node.allHosts.filter((h) => h.status === "online").length;
    const offline = node.allHosts.filter((h) => h.status === "offline").length;
    const ids = node.allHosts.map((h) => h.id);
    const allSelected = ids.length > 0 && ids.every((id) => selectedHostIds.includes(id));
    const someSelected = !allSelected && ids.some((id) => selectedHostIds.includes(id));
    const Icon = level === "building" ? Building2 : level === "floor" ? Layers : DoorOpen;

    return (
      <div
        className={
          level === "room"
            ? "flex items-center gap-3 border-b border-border bg-muted/40 px-4 py-2.5"
            : level === "building"
              ? "flex items-center gap-3 rounded-lg border border-border bg-muted/60 px-4 py-3"
              : "flex items-center gap-3 rounded-lg border border-border bg-muted/30 px-4 py-2"
        }
      >
        <button
          onClick={() => toggleGroupCollapsed(node.key)}
          className="flex items-center gap-2 text-left"
          aria-expanded={!collapsed}
          aria-label={collapsed ? `Развернуть ${node.name}` : `Свернуть ${node.name}`}
        >
          {collapsed ? (
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
          )}
          <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className={level === "building" ? "text-base font-semibold text-foreground" : "font-semibold text-foreground"}>
            {node.name}
          </span>
        </button>
        <span className="text-xs text-muted-foreground tabular-nums">{node.allHosts.length} ПК</span>
        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 dark:bg-emerald-400" />
          {online}
        </span>
        {offline > 0 && (
          <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
            <span className="h-1.5 w-1.5 rounded-full bg-rose-500 dark:bg-rose-400" />
            {offline}
          </span>
        )}
        {canEdit && (
          <button
            onClick={() => toggleGroupSelection(node.allHosts)}
            className="btn-ghost ml-auto inline-flex items-center gap-1.5 px-2 py-1 text-xs"
            title="Выбрать все хосты в этой группе"
          >
            {allSelected ? <CheckSquare className="h-3.5 w-3.5" /> : <Square className="h-3.5 w-3.5" />}
            {someSelected ? "Выбрать остальные" : allSelected ? "Снять выбор" : "Выбрать группу"}
          </button>
        )}
      </div>
    );
  }

  function renderGroupNode(node: GroupNode, depth: number) {
    const collapsed = !expandedGroups.has(node.key);

    // Аудитория (или любая группа без подгрупп) — карточка с таблицей ПК.
    if (node.children.length === 0) {
      return (
        <div key={node.key} className="table-shell">
          {renderGroupHeader(node, "room")}
          {!collapsed && renderHostTable(node.hosts, node.name)}
        </div>
      );
    }

    // Корпус или этаж — заголовок и вложенные группы с отступом.
    return (
      <div key={node.key} className="space-y-3">
        {renderGroupHeader(node, depth === 0 ? "building" : "floor")}
        {!collapsed && (
          <div className="ml-2 space-y-3 border-l border-border pl-4">
            {node.hosts.length > 0 && <div className="table-shell">{renderHostTable(node.hosts, node.name)}</div>}
            {node.children.map((child) => renderGroupNode(child, depth + 1))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="animate-fade-in space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Реестр хостов</h1>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant={filtersActive ? "primary" : "secondary"}
            size="sm"
            onClick={() => setShowFilters((v) => !v)}
            title={showFilters ? "Скрыть фильтры" : "Показать фильтры"}
          >
            <Filter className="h-3.5 w-3.5" />
            Фильтры{activeFilterCount > 0 ? ` (${activeFilterCount})` : ""}
          </Button>
          {groupKeys.length > 0 && (
            <Button variant="secondary" size="sm" onClick={toggleAllGroups}>
              {anyGroupExpanded ? <ChevronsDownUp className="h-3.5 w-3.5" /> : <ChevronsUpDown className="h-3.5 w-3.5" />}
              {anyGroupExpanded ? "Свернуть все" : "Развернуть все"}
            </Button>
          )}
          <Button variant="secondary" size="sm" onClick={downloadInventory}>
            <Download className="h-3.5 w-3.5" />
            Скачать inventory
          </Button>
          {canEdit && (
            <>
              <label
                className="btn-secondary btn-sm"
                tabIndex={0}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInputRef.current?.click(); } }}
              >
                <Upload className="h-3.5 w-3.5" />
                Импорт CSV
                <input ref={fileInputRef} type="file" accept=".csv" onChange={handleImport} className="sr-only" />
              </label>
              <Button size="sm" onClick={() => setShowForm((v) => !v)}>
                <Plus className="h-3.5 w-3.5" />
                Добавить хост
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Компактная сводка — заменяет одну плотную строку текста набором
          читаемых с одного взгляда чисел. */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 rounded-xl border border-border bg-surface px-4 py-2.5 text-sm shadow-panel">
        <span className="font-semibold text-foreground tabular-nums">{overallStats.total} хостов</span>
        <span className="inline-flex items-center gap-1.5 text-muted-foreground">
          <span className="h-2 w-2 shrink-0 rounded-full bg-emerald-500 dark:bg-emerald-400" />
          online <b className="text-foreground tabular-nums">{overallStats.online}</b>
        </span>
        <span className="inline-flex items-center gap-1.5 text-muted-foreground">
          <span className="h-2 w-2 shrink-0 rounded-full bg-rose-500 dark:bg-rose-400" />
          offline <b className="text-foreground tabular-nums">{overallStats.offline}</b>
        </span>
        <span className="hidden text-border sm:inline">·</span>
        <span className="text-muted-foreground">
          с агентом <b className="text-foreground tabular-nums">{overallStats.withAgent}</b>
        </span>
        {agentVersions && (
          <span className="text-muted-foreground">
            актуальных <b className="text-emerald-600 dark:text-emerald-400 tabular-nums">{agentVersions.up_to_date}</b>
            {" · "}устаревших <b className="text-amber-600 dark:text-amber-400 tabular-nums">{agentVersions.outdated}</b>
          </span>
        )}
        {agentVersions?.available_version && (
          <span className="ml-auto text-xs text-muted-foreground">
            версия агента: <span className="font-mono text-foreground">{agentVersions.available_version}</span>
          </span>
        )}
      </div>

      {importResult && <p className="text-sm text-muted-foreground">{importResult}</p>}

      {showForm && canEdit && (
        <form onSubmit={handleCreate} className="surface-panel grid animate-slide-up grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <div>
            <label htmlFor="host-ip" className="field-label">IP-адрес</label>
            <input id="host-ip" value={form.ip_address} onChange={(e) => setForm({ ...form, ip_address: e.target.value })} className="input-base font-mono" placeholder="10.40.1.20" />
          </div>
          <div>
            <label htmlFor="host-hostname" className="field-label">Hostname</label>
            <input id="host-hostname" value={form.hostname} onChange={(e) => setForm({ ...form, hostname: e.target.value })} className="input-base" placeholder="pc-01.example.local" />
          </div>
          <div>
            <label htmlFor="host-os" className="field-label">ОС</label>
            <select id="host-os" value={form.os} onChange={(e) => setForm({ ...form, os: e.target.value })} className="input-base">
              {OS_OPTIONS.map((o) => <option key={o} value={o}>{osLabel(o)}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="host-group" className="field-label">Группа</label>
            <select id="host-group" value={form.group_id} onChange={(e) => setForm({ ...form, group_id: e.target.value })} className="input-base">
              <option value="">Без группы</option>
              {groupTree.options.map((g) => <option key={g.id} value={g.id}>{g.label}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="host-cred" className="field-label">Credentials</label>
            <select id="host-cred" value={form.credential_id} onChange={(e) => setForm({ ...form, credential_id: e.target.value })} className="input-base">
              <option value="">Без credentials</option>
              {credentials.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="host-comment" className="field-label">Комментарий</label>
            <input id="host-comment" value={form.comment} onChange={(e) => setForm({ ...form, comment: e.target.value })} className="input-base" />
          </div>
          <Button type="submit" className="sm:col-span-2 lg:col-span-3">Сохранить</Button>
          {hostFormError && <p className="text-sm text-red-500 sm:col-span-2 lg:col-span-3">{hostFormError}</p>}
        </form>
      )}

      {showFilters && (
        <section className="surface-panel animate-slide-up">
          <div className="flex flex-wrap items-end gap-3">
            <div className="w-40">
              <label className="field-label">Hostname</label>
              <input
                value={filters.hostname}
                onChange={(e) => updateFilter("hostname", e.target.value)}
                className="input-base"
                placeholder="Поиск…"
              />
            </div>
            <div className="w-40">
              <label className="field-label">IP</label>
              <input
                value={filters.ip}
                onChange={(e) => updateFilter("ip", e.target.value)}
                className="input-base font-mono"
                placeholder="Поиск…"
              />
            </div>
            <div className="w-64">
              <label className="field-label">Группа</label>
              <select value={filters.group} onChange={(e) => updateFilter("group", e.target.value)} className="input-base">
                <option value="">Все</option>
                <option value={NO_GROUP}>{NO_GROUP_LABEL}</option>
                {groupTree.options.map((g) => <option key={g.id} value={g.id}>{g.label}</option>)}
              </select>
            </div>
            <div className="w-36">
              <label className="field-label">ОС</label>
              <select value={filters.os} onChange={(e) => updateFilter("os", e.target.value)} className="input-base">
                <option value="">Все</option>
                {OS_OPTIONS.map((o) => <option key={o} value={o}>{osLabel(o)}</option>)}
              </select>
            </div>
            <div className="w-32">
              <label className="field-label">Статус</label>
              <select value={filters.status} onChange={(e) => updateFilter("status", e.target.value)} className="input-base">
                <option value="">Все</option>
                {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div className="w-40">
              <label className="field-label">Агент</label>
              <select value={filters.agent} onChange={(e) => updateFilter("agent", e.target.value)} className="input-base">
                <option value="">Все</option>
                {AGENT_FILTER_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
            <div className="w-40">
              <label className="field-label">Проверен</label>
              <select value={filters.checked} onChange={(e) => updateFilter("checked", e.target.value)} className="input-base">
                <option value="">Все</option>
                {CHECKED_FILTER_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
            {filtersActive && (
              <button
                onClick={() => setFilters(EMPTY_FILTERS)}
                className="btn-ghost inline-flex items-center gap-1.5 px-2.5 py-2 text-xs"
                title="Сбросить фильтры"
              >
                <XCircle className="h-3.5 w-3.5" />
                Сбросить
              </button>
            )}
            {canEdit && visibleCount > 0 && (
              <button
                onClick={toggleAllVisibleHosts}
                className="btn-ghost ml-auto inline-flex items-center gap-1.5 px-2.5 py-2 text-xs"
                title="Выбрать все хосты, подходящие под текущие фильтры"
              >
                {allVisibleSelected ? <CheckSquare className="h-3.5 w-3.5" /> : <Square className="h-3.5 w-3.5" />}
                {allVisibleSelected ? "Снять выбор со всех" : `Выбрать все видимые (${visibleCount})`}
              </button>
            )}
          </div>
        </section>
      )}

      {canEdit && selectedHostIds.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-blue-500/30 bg-blue-500/5 px-4 py-2.5 text-sm">
          <CheckSquare className="h-4 w-4 shrink-0 text-blue-600 dark:text-blue-400" />
          <span className="font-medium text-foreground">Выбрано: {selectedHostIds.length}</span>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => { setShowGroupPanel((value) => !value); setGroupError(null); }}
            >
              <FolderPlus className="h-3.5 w-3.5" />
              Группа
            </Button>
            <Button
              variant="secondary"
              size="sm"
              loading={agentBusy === "scan"}
              onClick={() => startAgentTask(
                "scan",
                selectedAgentHostIds(),
                selectedAgentHostIds().length ? "Проверка версий агента на выбранных хостах" : "Проверка версий агента на всех хостах",
              )}
              title="Опросить хосты по SSH и обновить установленные версии агента"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Версии агента
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={selectedAgentHostIds().length === 0}
              loading={agentBusy === "update"}
              onClick={() => startAgentTask(
                "update",
                selectedAgentHostIds(),
                `Обновление агента (${selectedAgentHostIds().length} хост(ов))`,
              )}
              title={
                agentVersions?.installer_present
                  ? `Установить версию ${agentVersions.available_version ?? "из папки установочников"}`
                  : "Установщик агента ещё не синхронизирован с сервером"
              }
            >
              <ArrowUpCircle className="h-3.5 w-3.5" />
              Обновить агент ({selectedAgentHostIds().length})
            </Button>
            <button className="btn-ghost btn-sm" onClick={() => setSelectedHostIds([])}>
              <X className="h-3.5 w-3.5" />
              Снять выбор
            </button>
          </div>
        </div>
      )}

      {showGroupPanel && canEdit && (
        <section className="surface-panel animate-slide-up space-y-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-foreground">Изменить группу</h2>
              <p className="text-sm text-muted-foreground">Выбрано хостов: {selectedHostIds.length}</p>
            </div>
            <button className="btn-ghost p-1" onClick={() => setShowGroupPanel(false)} aria-label="Закрыть выбор группы">
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className="field-label">Существующая группа</label>
              <select value={groupTarget} onChange={(event) => { setGroupTarget(event.target.value); setNewGroupName(""); }} className="input-base">
                <option value="">Создать новую группу</option>
                <option value={NO_GROUP_TARGET}>{NO_GROUP_LABEL} (убрать из текущей)</option>
                {groupTree.options.map((group) => <option key={group.id} value={group.id}>{group.label}</option>)}
              </select>
            </div>
            {!groupTarget && (
              <div>
                <label className="field-label">Имя новой группы</label>
                <input value={newGroupName} onChange={(event) => setNewGroupName(event.target.value)} className="input-base" placeholder="Например, MR32-311" />
              </div>
            )}
          </div>
          {groupError && <p className="text-sm text-red-500">{groupError}</p>}
          <Button onClick={assignSelectedHosts} loading={groupSaving}>
            <CheckSquare className="h-4 w-4" />
            {groupTarget === NO_GROUP_TARGET ? "Убрать выбранные хосты из группы" : "Назначить выбранные хосты"}
          </Button>
        </section>
      )}

      {diagnosticHost && canEdit && (
        <section className="surface-panel animate-slide-up space-y-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-foreground">Диагностика подключения</h2>
              <p className="text-sm text-muted-foreground">
                {diagnosticHost.hostname || diagnosticHost.ip_address || "Хост"}
              </p>
            </div>
            <button className="btn-ghost p-1" onClick={() => { setDiagnosticHost(null); setDiagnosticTask(null); setDiagnosticError(null); }} aria-label="Закрыть диагностику">
              <X className="h-4 w-4" />
            </button>
          </div>
          {diagnosticStarting && <p className="text-sm text-muted-foreground">Запуск проверки…</p>}
          {diagnosticError && <p className="text-sm text-red-500">{diagnosticError}</p>}
          {diagnosticTask && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-sm">
                <span className="text-muted-foreground">Статус:</span>
                <Badge status={diagnosticTask.status} />
              </div>
              {["queued", "running"].includes(diagnosticTask.status) ? (
                <TaskLog taskId={diagnosticTask.id} />
              ) : (
                <pre className="console-block">{diagnosticTask.log_output || "Лог пуст"}</pre>
              )}
            </div>
          )}
        </section>
      )}

      {(agentTask || agentError) && canEdit && (
        <section className="surface-panel animate-slide-up space-y-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-foreground">Обслуживание агента</h2>
              <p className="text-sm text-muted-foreground">{agentTaskTitle}</p>
            </div>
            <button
              className="btn-ghost p-1"
              onClick={() => { setAgentTask(null); setAgentError(null); }}
              aria-label="Закрыть панель обслуживания агента"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          {agentError && <p className="text-sm text-red-500">{agentError}</p>}
          {agentTask && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-sm">
                <span className="text-muted-foreground">Статус:</span>
                <Badge status={agentTask.status} />
              </div>
              {["queued", "running"].includes(agentTask.status) ? (
                <TaskLog taskId={agentTask.id} />
              ) : (
                <pre className="console-block">{agentTask.log_output || "Лог пуст"}</pre>
              )}
            </div>
          )}
        </section>
      )}

      {/* Хосты разложены деревом групп: корпус > этаж > аудитория. Каждый
          уровень сворачивается и несёт мини-сводку online/offline. */}
      <div className="space-y-4">
        {groupNodes.map((node) => renderGroupNode(node, 0))}
        {groupNodes.length === 0 && (
          <div className="table-shell">
            <p className="px-4 py-8 text-center text-subtle">
              {hosts.length === 0 ? "Хостов нет" : "Ничего не найдено по заданным фильтрам"}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
