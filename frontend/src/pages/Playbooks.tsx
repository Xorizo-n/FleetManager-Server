import { FormEvent, useEffect, useState } from "react";
import { GitBranch, Play, Plus, Trash2 } from "lucide-react";
import { apiClient } from "../api/client";
import { useAuth } from "../context/AuthContext";
import Badge from "../components/ui/Badge";
import Button from "../components/ui/Button";

interface Repo {
  id: string;
  name: string;
  git_url: string;
  branch: string;
}

interface PlaybookFile {
  name: string;
  path: string;
}

interface Host {
  id: string;
  hostname: string;
}

interface HostGroup {
  id: string;
  name: string;
}

interface Schedule {
  id: string;
  repo_id: string;
  playbook_name: string;
  host_group_id: string | null;
  cron_expression: string;
  enabled: boolean;
}

interface CredentialOption {
  id: string;
  name: string;
  type: "ssh_key" | "password" | "token";
}

interface ExtraVarPair {
  key: string;
  value: string;
}

export default function Playbooks() {
  const { user } = useAuth();
  const canEdit = user?.role === "admin" || user?.role === "operator";

  const [repos, setRepos] = useState<Repo[]>([]);
  const [files, setFiles] = useState<PlaybookFile[]>([]);
  const [hosts, setHosts] = useState<Host[]>([]);
  const [groups, setGroups] = useState<HostGroup[]>([]);
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [credentials, setCredentials] = useState<CredentialOption[]>([]);

  const [showRepoForm, setShowRepoForm] = useState(false);
  const [repoForm, setRepoForm] = useState({ name: "", git_url: "", git_token: "", credential_id: "", branch: "main" });
  const [repoFormError, setRepoFormError] = useState<string | null>(null);

  const sshCredentials = credentials.filter((c) => c.type === "ssh_key");
  const isSshUrl = /^(git@|ssh:\/\/)/.test(repoForm.git_url.trim());

  const [selectedRepoId, setSelectedRepoId] = useState("");
  const [selectedPlaybook, setSelectedPlaybook] = useState("");
  const [selectedHostIds, setSelectedHostIds] = useState<string[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState("");
  const [extraVars, setExtraVars] = useState<ExtraVarPair[]>([{ key: "", value: "" }]);
  const [runMessage, setRunMessage] = useState<string | null>(null);

  const [cronExpression, setCronExpression] = useState("0 3 * * *");

  async function loadRepos() {
    const { data } = await apiClient.get<Repo[]>("/playbooks/repos");
    setRepos(data);
  }

  async function loadHostsAndGroups() {
    const [h, g] = await Promise.all([apiClient.get<Host[]>("/hosts"), apiClient.get<HostGroup[]>("/hosts/groups")]);
    setHosts(h.data);
    setGroups(g.data);
  }

  async function loadSchedules() {
    const { data } = await apiClient.get<Schedule[]>("/playbooks/schedules");
    setSchedules(data);
  }

  async function loadCredentials() {
    try {
      const { data } = await apiClient.get<CredentialOption[]>("/credentials");
      setCredentials(data);
    } catch {
      setCredentials([]);
    }
  }

  useEffect(() => {
    loadRepos();
    loadHostsAndGroups();
    loadSchedules();
    loadCredentials();
  }, []);

  useEffect(() => {
    if (!selectedRepoId) {
      setFiles([]);
      return;
    }
    apiClient.get<PlaybookFile[]>(`/playbooks/repos/${selectedRepoId}/files`).then((r) => setFiles(r.data));
  }, [selectedRepoId]);

  async function handleAddRepo(e: FormEvent) {
    e.preventDefault();
    setRepoFormError(null);
    try {
      await apiClient.post("/playbooks/repos", {
        ...repoForm,
        credential_id: repoForm.credential_id || null,
      });
      setRepoForm({ name: "", git_url: "", git_token: "", credential_id: "", branch: "main" });
      setShowRepoForm(false);
      loadRepos();
    } catch (err: any) {
      setRepoFormError(err.response?.data?.detail || "Не удалось подключить репозиторий");
    }
  }

  function toggleHost(id: string) {
    setSelectedHostIds((prev) => (prev.includes(id) ? prev.filter((h) => h !== id) : [...prev, id]));
  }

  function updateExtraVar(index: number, field: "key" | "value", value: string) {
    setExtraVars((prev) => prev.map((pair, i) => (i === index ? { ...pair, [field]: value } : pair)));
  }

  function buildExtraVarsObject(): Record<string, string> {
    return Object.fromEntries(extraVars.filter((p) => p.key.trim()).map((p) => [p.key.trim(), p.value]));
  }

  async function handleRun() {
    if (!selectedRepoId || !selectedPlaybook) return;
    const { data } = await apiClient.post("/playbooks/run", {
      repo_id: selectedRepoId,
      playbook_name: selectedPlaybook,
      host_ids: selectedHostIds,
      host_group_id: selectedGroupId || null,
      extra_vars: buildExtraVarsObject(),
    });
    setRunMessage(`Запущено, задача: ${data.task_run_id}`);
  }

  async function handleCreateSchedule() {
    if (!selectedRepoId || !selectedPlaybook) return;
    await apiClient.post("/playbooks/schedules", {
      repo_id: selectedRepoId,
      playbook_name: selectedPlaybook,
      host_group_id: selectedGroupId || null,
      host_ids: selectedHostIds,
      extra_vars: buildExtraVarsObject(),
      cron_expression: cronExpression,
      enabled: true,
    });
    loadSchedules();
  }

  async function handleDeleteSchedule(id: string) {
    if (!window.confirm("Удалить расписание?")) return;
    await apiClient.delete(`/playbooks/schedules/${id}`);
    loadSchedules();
  }

  function repoName(id: string) {
    return repos.find((r) => r.id === id)?.name || id;
  }

  return (
    <div className="animate-fade-in space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Плейбуки</h1>
        {canEdit && (
          <Button size="sm" onClick={() => setShowRepoForm((v) => !v)}>
            <GitBranch className="h-3.5 w-3.5" />
            Подключить репозиторий
          </Button>
        )}
      </div>

      {showRepoForm && canEdit && (
        <form onSubmit={handleAddRepo} className="surface-panel grid animate-slide-up grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label className="field-label">Название</label>
            <input required value={repoForm.name} onChange={(e) => setRepoForm({ ...repoForm, name: e.target.value })} className="input-base" />
          </div>
          <div>
            <label className="field-label">Git URL</label>
            <input
              required
              placeholder="https://... или git@host:group/repo.git"
              value={repoForm.git_url}
              onChange={(e) => setRepoForm({ ...repoForm, git_url: e.target.value })}
              className="input-base font-mono"
            />
          </div>

          {isSshUrl ? (
            <div>
              <label className="field-label">SSH-ключ из Key Store</label>
              <select
                required
                value={repoForm.credential_id}
                onChange={(e) => setRepoForm({ ...repoForm, credential_id: e.target.value })}
                className="input-base"
              >
                <option value="">Выберите ключ</option>
                {sshCredentials.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              {sshCredentials.length === 0 && (
                <p className="mt-1 text-xs text-amber-500">
                  Нет SSH-ключей в Key Store — добавьте credential типа "SSH-ключ" на странице Key Store
                </p>
              )}
            </div>
          ) : (
            <div>
              <label className="field-label">Токен доступа (опционально)</label>
              <input value={repoForm.git_token} onChange={(e) => setRepoForm({ ...repoForm, git_token: e.target.value })} className="input-base" />
            </div>
          )}

          <div>
            <label className="field-label">Ветка</label>
            <input value={repoForm.branch} onChange={(e) => setRepoForm({ ...repoForm, branch: e.target.value })} className="input-base" />
          </div>

          {repoFormError && <p className="text-sm text-red-500 sm:col-span-2">{repoFormError}</p>}
          <Button type="submit" className="sm:col-span-2">Подключить</Button>
        </form>
      )}

      <div className="surface-panel space-y-3">
        <h2 className="text-sm font-medium text-muted-foreground">Запуск плейбука</h2>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <select value={selectedRepoId} onChange={(e) => setSelectedRepoId(e.target.value)} className="input-base">
            <option value="">Выберите репозиторий</option>
            {repos.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
          <select value={selectedPlaybook} onChange={(e) => setSelectedPlaybook(e.target.value)} className="input-base">
            <option value="">Выберите плейбук</option>
            {files.map((f) => <option key={f.path} value={f.path}>{f.path}</option>)}
          </select>
        </div>

        <div>
          <p className="mb-1 text-xs text-subtle">Хосты (или выберите группу целиком)</p>
          <div className="flex flex-wrap gap-2">
            <select value={selectedGroupId} onChange={(e) => setSelectedGroupId(e.target.value)} className="input-base w-auto px-2 py-1 text-xs">
              <option value="">Без группы</option>
              {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select>
            {hosts.map((h) => (
              <label key={h.id} className={selectedHostIds.includes(h.id) ? "chip-on" : "chip-off"}>
                <input type="checkbox" className="sr-only" checked={selectedHostIds.includes(h.id)} onChange={() => toggleHost(h.id)} />
                {h.hostname}
              </label>
            ))}
          </div>
        </div>

        <div>
          <p className="mb-1 text-xs text-subtle">Extra variables</p>
          <div className="space-y-2">
            {extraVars.map((pair, i) => (
              <div key={i} className="flex gap-2">
                <input placeholder="key" value={pair.key} onChange={(e) => updateExtraVar(i, "key", e.target.value)} className="input-base w-1/3 py-1.5 text-sm font-mono" />
                <input placeholder="value" value={pair.value} onChange={(e) => updateExtraVar(i, "value", e.target.value)} className="input-base flex-1 py-1.5 text-sm" />
              </div>
            ))}
            <button type="button" onClick={() => setExtraVars((prev) => [...prev, { key: "", value: "" }])} className="text-xs text-blue-600 transition-colors hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300">
              + переменная
            </button>
          </div>
        </div>

        {canEdit && (
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <Button onClick={handleRun} disabled={!selectedRepoId || !selectedPlaybook}>
              <Play className="h-3.5 w-3.5" />
              Запустить сейчас
            </Button>
            <input value={cronExpression} onChange={(e) => setCronExpression(e.target.value)} className="input-base w-auto py-1.5 text-sm font-mono" placeholder="0 3 * * *" />
            <Button variant="secondary" onClick={handleCreateSchedule} disabled={!selectedRepoId || !selectedPlaybook}>
              Добавить расписание
            </Button>
          </div>
        )}

        {runMessage && <p className="text-sm text-muted-foreground">{runMessage}</p>}
      </div>

      <div className="table-shell">
        <table className="table-base">
          <thead>
            <tr>
              <th>Репозиторий</th>
              <th>Плейбук</th>
              <th>Cron</th>
              <th>Статус</th>
              {canEdit && <th className="text-right">Действия</th>}
            </tr>
          </thead>
          <tbody>
            {schedules.map((s) => (
              <tr key={s.id}>
                <td>{repoName(s.repo_id)}</td>
                <td className="text-foreground/80">{s.playbook_name}</td>
                <td className="font-mono text-foreground/80">{s.cron_expression}</td>
                <td><Badge status={s.enabled ? "success" : "disabled"}>{s.enabled ? "включено" : "выключено"}</Badge></td>
                {canEdit && (
                  <td className="text-right">
                    <button
                      onClick={() => handleDeleteSchedule(s.id)}
                      className="action-danger"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      Удалить
                    </button>
                  </td>
                )}
              </tr>
            ))}
            {schedules.length === 0 && (
              <tr><td colSpan={5} className="px-3 py-8 text-center text-subtle">Расписаний нет</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
