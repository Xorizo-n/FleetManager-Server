import { FormEvent, useEffect, useRef, useState } from "react";
import { Activity, ArrowUpCircle, CheckSquare, Download, FolderPlus, Plus, RefreshCw, Trash2, Upload, X } from "lucide-react";
import { apiClient, getAccessToken } from "../api/client";
import { useAuth } from "../context/AuthContext";
import Badge from "../components/ui/Badge";
import Button from "../components/ui/Button";
import TaskLog from "../components/TaskLog";

interface HostGroup {
  id: string;
  name: string;
  description: string | null;
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

export default function Hosts() {
  const { user } = useAuth();
  const canEdit = user?.role === "admin" || user?.role === "operator";

  const [hosts, setHosts] = useState<Host[]>([]);
  const [groups, setGroups] = useState<HostGroup[]>([]);
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [groupFilter, setGroupFilter] = useState("");
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
    const { data } = await apiClient.get<Host[]>("/hosts", {
      params: groupFilter ? { group_id: groupFilter } : {},
    });
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
    loadGroups();
    loadCredentials();
    loadAgentVersions();
  }, []);

  useEffect(() => {
    loadHosts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groupFilter]);

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
    const visibleIds = hosts.map((host) => host.id);
    const allSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedHostIds.includes(id));
    setSelectedHostIds(allSelected ? [] : visibleIds);
  }

  async function assignSelectedHosts() {
    if (selectedHostIds.length === 0) return;
    const groupName = newGroupName.trim();
    if (!groupTarget && !groupName) {
      setGroupError("Выберите существующую группу или укажите имя новой");
      return;
    }
    setGroupError(null);
    setGroupSaving(true);
    try {
      await apiClient.post("/hosts/groups/assign", {
        host_ids: selectedHostIds,
        ...(groupTarget ? { group_id: groupTarget } : { group_name: groupName }),
      });
      await Promise.all([loadGroups(), loadHosts()]);
      setSelectedHostIds([]);
      setShowGroupPanel(false);
      setGroupTarget("");
      setNewGroupName("");
    } catch (err: any) {
      setGroupError(err.response?.data?.detail || "Не удалось добавить хосты в группу");
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

  function groupName(id: string | null) {
    return groups.find((g) => g.id === id)?.name || "—";
  }

  return (
    <div className="animate-fade-in space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Реестр хостов</h1>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={groupFilter}
            onChange={(e) => setGroupFilter(e.target.value)}
            className="input-base w-auto py-2 text-sm"
          >
            <option value="">Все группы</option>
            {groups.map((g) => (
              <option key={g.id} value={g.id}>{g.name}</option>
            ))}
          </select>
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
              <Button
                variant="secondary"
                size="sm"
                disabled={selectedHostIds.length === 0}
                onClick={() => { setShowGroupPanel((value) => !value); setGroupError(null); }}
              >
                <FolderPlus className="h-3.5 w-3.5" />
                В группу ({selectedHostIds.length})
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
                Проверить версии агента
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
            </>
          )}
        </div>
      </div>

      {agentVersions && (
        <p className="text-sm text-muted-foreground">
          Доступная версия агента: <span className="font-mono text-foreground">{agentVersions.available_version ?? "неизвестна"}</span>
          {" · "}актуальных: {agentVersions.up_to_date}
          {" · "}устаревших: {agentVersions.outdated}
          {" · "}без данных: {agentVersions.unknown}
          {" · "}всего с агентом: {agentVersions.total_agents}
        </p>
      )}

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
              {OS_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="host-group" className="field-label">Группа</label>
            <select id="host-group" value={form.group_id} onChange={(e) => setForm({ ...form, group_id: e.target.value })} className="input-base">
              <option value="">Без группы</option>
              {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
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

      {showGroupPanel && canEdit && (
        <section className="surface-panel animate-slide-up space-y-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-foreground">Добавить хосты в группу</h2>
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
                {groups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}
              </select>
            </div>
            {!groupTarget && (
              <div>
                <label className="field-label">Имя новой группы</label>
                <input value={newGroupName} onChange={(event) => setNewGroupName(event.target.value)} className="input-base" placeholder="Например, Бухгалтерия" />
              </div>
            )}
          </div>
          {groupError && <p className="text-sm text-red-500">{groupError}</p>}
          <Button onClick={assignSelectedHosts} loading={groupSaving}>
            <CheckSquare className="h-4 w-4" />
            Назначить выбранные хосты
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

      <div className="table-shell">
        <table className="table-base">
          <thead>
            <tr>
              {canEdit && (
                <th className="w-10">
                  <input
                    type="checkbox"
                    checked={hosts.length > 0 && hosts.every((host) => selectedHostIds.includes(host.id))}
                    onChange={toggleAllVisibleHosts}
                    aria-label="Выбрать все хосты"
                  />
                </th>
              )}
              <th>Hostname</th>
              <th>IP</th>
              <th>Группа</th>
              <th>OS</th>
              <th>Статус</th>
              <th>Агент</th>
              <th>Проверен</th>
              {canEdit && <th className="text-right">Действия</th>}
            </tr>
          </thead>
          <tbody>
            {hosts.map((h) => (
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
                <td>{groupName(h.group_id)}</td>
                <td>{h.os}</td>
                <td><Badge status={h.status} /></td>
                <td>
                  {h.has_agent ? (
                    <div className="flex flex-col gap-1">
                      <span className="font-mono text-foreground/80">
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
                <td className="text-muted-foreground">
                  {h.last_checked_at ? new Date(h.last_checked_at).toLocaleString() : "—"}
                </td>
                {canEdit && (
                  <td className="text-right">
                    {h.has_agent && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => startAgentTask("update", [h.id], `Обновление агента: ${h.hostname || h.ip_address || h.id}`)}
                        className="mr-2"
                      >
                        <ArrowUpCircle className="h-3.5 w-3.5" />
                        Обновить агент
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => startDiagnostic(h)}
                      loading={diagnosticStarting && diagnosticHost?.id === h.id}
                      className="mr-2"
                    >
                      <Activity className="h-3.5 w-3.5" />
                      Диагностика
                    </Button>
                    <button
                      onClick={() => handleDelete(h.id)}
                      className="action-danger"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      Удалить
                    </button>
                  </td>
                )}
              </tr>
            ))}
            {hosts.length === 0 && (
              <tr>
                <td colSpan={canEdit ? 9 : 7} className="px-3 py-8 text-center text-subtle">Хостов нет</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
