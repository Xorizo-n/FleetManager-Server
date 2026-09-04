import { FormEvent, useEffect, useRef, useState } from "react";
import { ChevronDown, GitBranch, Play, RefreshCw, Search, Trash2, X } from "lucide-react";
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
  display_name?: string;
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

function prettyName(path: string): string {
  const base = path.split("/").pop()?.replace(/\.(yml|yaml)$/, "") ?? path;
  return base.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function fileFolder(path: string): string {
  const parts = path.split("/");
  return parts.length > 1 ? parts[0] : "";
}

function groupByFolder(files: PlaybookFile[]): [string, PlaybookFile[]][] {
  const map = new Map<string, PlaybookFile[]>();
  for (const f of files) {
    const folder = fileFolder(f.path);
    const group = map.get(folder) ?? [];
    group.push(f);
    map.set(folder, group);
  }
  return Array.from(map.entries());
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
  const [syncingRepoId, setSyncingRepoId] = useState<string | null>(null);

  const sshCredentials = credentials.filter((c) => c.type === "ssh_key");
  const isSshUrl = /^(git@|ssh:\/\/)/.test(repoForm.git_url.trim());

  const [selectedRepoId, setSelectedRepoId] = useState("");
  const [selectedPlaybook, setSelectedPlaybook] = useState("");
  const [selectedHostIds, setSelectedHostIds] = useState<string[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState("");
  const [extraVars, setExtraVars] = useState<ExtraVarPair[]>([{ key: "", value: "" }]);
  const [runMessage, setRunMessage] = useState<string | null>(null);
  const [cronExpression, setCronExpression] = useState("0 3 * * *");

  const [comboOpen, setComboOpen] = useState(false);
  const [comboSearch, setComboSearch] = useState("");
  const comboRef = useRef<HTMLDivElement>(null);
  const comboInputRef = useRef<HTMLInputElement>(null);

  async function loadRepos() {
    const { data } = await apiClient.get<Repo[]>("/playbooks/repos");
    setRepos(data);
    if (data.length === 1) setSelectedRepoId(data[0].id);
  }

  async function loadHostsAndGroups() {
    const [h, g] = await Promise.all([
      apiClient.get<Host[]>("/hosts"),
      apiClient.get<HostGroup[]>("/hosts/groups"),
    ]);
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
      setSelectedPlaybook("");
      return;
    }
    apiClient
      .get<PlaybookFile[]>(`/playbooks/repos/${selectedRepoId}/files`)
      .then((r) => setFiles(r.data));
  }, [selectedRepoId]);

  useEffect(() => {
    if (!comboOpen) return;
    function handler(e: MouseEvent) {
      if (comboRef.current && !comboRef.current.contains(e.target as Node)) {
        setComboOpen(false);
      }
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [comboOpen]);

  useEffect(() => {
    if (comboOpen) comboInputRef.current?.focus();
  }, [comboOpen]);

  const filteredFiles = comboSearch
    ? files.filter((f) => {
        const q = comboSearch.toLowerCase();
        const label = f.display_name || prettyName(f.path);
        return f.path.toLowerCase().includes(q) || label.toLowerCase().includes(q);
      })
    : files;

  const fileGroups = groupByFolder(filteredFiles);

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

  async function handleSync(repoId: string) {
    setSyncingRepoId(repoId);
    try {
      await apiClient.post(`/playbooks/repos/${repoId}/sync`);
      if (repoId === selectedRepoId) {
        const { data } = await apiClient.get<PlaybookFile[]>(`/playbooks/repos/${repoId}/files`);
        setFiles(data);
      }
    } finally {
      setSyncingRepoId(null);
    }
  }

  function toggleHost(id: string) {
    setSelectedHostIds((prev) =>
      prev.includes(id) ? prev.filter((h) => h !== id) : [...prev, id]
    );
  }

  function updateExtraVar(index: number, field: "key" | "value", value: string) {
    setExtraVars((prev) => prev.map((pair, i) => (i === index ? { ...pair, [field]: value } : pair)));
  }

  function buildExtraVarsObject(): Record<string, string> {
    return Object.fromEntries(
      extraVars.filter((p) => p.key.trim()).map((p) => [p.key.trim(), p.value])
    );
  }

  async function handleRun() {
    if (!selectedRepoId || !selectedPlaybook) return;
    setRunMessage(null);
    const { data } = await apiClient.post("/playbooks/run", {
      repo_id: selectedRepoId,
      playbook_name: selectedPlaybook,
      host_ids: selectedHostIds,
      host_group_id: selectedGroupId || null,
      extra_vars: buildExtraVarsObject(),
    });
    setRunMessage(`Задача запущена: ${data.task_run_id}`);
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

  const selectedFile = files.find((f) => f.path === selectedPlaybook);
  const canRun = !!(selectedRepoId && selectedPlaybook);

  return (
    <div className="animate-fade-in space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Плейбуки</h1>
        {canEdit && (
          <Button size="sm" variant="secondary" onClick={() => setShowRepoForm((v) => !v)}>
            <GitBranch className="h-3.5 w-3.5" />
            {showRepoForm ? "Отмена" : "Подключить репозиторий"}
          </Button>
        )}
      </div>

      {/* Add repo form */}
      {showRepoForm && canEdit && (
        <form
          onSubmit={handleAddRepo}
          className="surface-panel grid animate-slide-up grid-cols-1 gap-3 sm:grid-cols-2"
        >
          <div>
            <label className="field-label">Название</label>
            <input
              required
              value={repoForm.name}
              onChange={(e) => setRepoForm({ ...repoForm, name: e.target.value })}
              className="input-base"
            />
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
                {sshCredentials.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
              {sshCredentials.length === 0 && (
                <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">
                  Нет SSH-ключей — добавьте credential типа «SSH-ключ» на странице Key Store
                </p>
              )}
            </div>
          ) : (
            <div>
              <label className="field-label">Токен доступа (опционально)</label>
              <input
                value={repoForm.git_token}
                onChange={(e) => setRepoForm({ ...repoForm, git_token: e.target.value })}
                className="input-base"
              />
            </div>
          )}
          <div>
            <label className="field-label">Ветка</label>
            <input
              value={repoForm.branch}
              onChange={(e) => setRepoForm({ ...repoForm, branch: e.target.value })}
              className="input-base"
            />
          </div>
          {repoFormError && (
            <p className="text-sm text-rose-600 sm:col-span-2">{repoFormError}</p>
          )}
          <Button type="submit" className="sm:col-span-2">
            Подключить
          </Button>
        </form>
      )}

      {/* Run panel */}
      <div className="surface-panel space-y-5">
        <h2 className="text-sm font-semibold text-foreground">Запуск плейбука</h2>

        {/* Repo: single — show as bar with sync; multiple — show select */}
        {repos.length === 0 && (
          <p className="text-sm text-subtle">Нет подключённых репозиториев</p>
        )}

        {repos.length === 1 && (
          <div className="flex items-center justify-between rounded-lg border border-border bg-muted/40 px-3 py-2">
            <div className="flex items-center gap-2 min-w-0">
              <GitBranch className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <span className="text-sm font-medium text-foreground truncate">{repos[0].name}</span>
              <span className="font-mono text-xs text-subtle shrink-0">{repos[0].branch}</span>
            </div>
            {canEdit && (
              <button
                type="button"
                onClick={() => handleSync(repos[0].id)}
                disabled={syncingRepoId === repos[0].id}
                className="btn-ghost btn-sm ml-2 shrink-0 gap-1.5 text-xs"
              >
                <RefreshCw className={`h-3 w-3 ${syncingRepoId === repos[0].id ? "animate-spin" : ""}`} />
                Обновить
              </button>
            )}
          </div>
        )}

        {repos.length > 1 && (
          <div>
            <label className="field-label">Репозиторий</label>
            <div className="flex gap-2">
              <select
                value={selectedRepoId}
                onChange={(e) => {
                  setSelectedRepoId(e.target.value);
                  setSelectedPlaybook("");
                }}
                className="input-base"
              >
                <option value="">Выберите репозиторий</option>
                {repos.map((r) => (
                  <option key={r.id} value={r.id}>{r.name}</option>
                ))}
              </select>
              {selectedRepoId && canEdit && (
                <button
                  type="button"
                  onClick={() => handleSync(selectedRepoId)}
                  disabled={syncingRepoId === selectedRepoId}
                  className="btn-ghost btn-sm shrink-0"
                  title="Обновить из git"
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${syncingRepoId === selectedRepoId ? "animate-spin" : ""}`} />
                </button>
              )}
            </div>
          </div>
        )}

        {/* Playbook combobox */}
        {selectedRepoId && (
          <div>
            <label className="field-label">Плейбук</label>
            <div ref={comboRef} className="relative">
              <button
                type="button"
                onClick={() => { setComboOpen((v) => !v); setComboSearch(""); }}
                className={`input-base flex w-full items-center justify-between text-left ${!selectedPlaybook ? "text-subtle" : ""}`}
              >
                {selectedFile ? (
                  <span className="flex items-center gap-2.5 min-w-0">
                    <span className="font-medium text-foreground truncate">
                      {selectedFile.display_name || prettyName(selectedFile.path)}
                    </span>
                    <span className="font-mono text-xs text-subtle shrink-0 hidden sm:inline">
                      {selectedFile.path}
                    </span>
                  </span>
                ) : (
                  <span>Выберите плейбук</span>
                )}
                <ChevronDown
                  className={`h-4 w-4 ml-2 shrink-0 text-muted-foreground transition-transform duration-150 ${comboOpen ? "rotate-180" : ""}`}
                />
              </button>

              {comboOpen && (
                <div className="animate-scale-in absolute left-0 right-0 top-full z-50 mt-1 overflow-hidden rounded-xl border border-border bg-surface shadow-panel-lg">
                  <div className="flex items-center gap-2 border-b border-border px-3 py-2">
                    <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <input
                      ref={comboInputRef}
                      value={comboSearch}
                      onChange={(e) => setComboSearch(e.target.value)}
                      onKeyDown={(e) => e.key === "Escape" && setComboOpen(false)}
                      placeholder="Поиск плейбука..."
                      className="flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-subtle"
                    />
                    {comboSearch && (
                      <button
                        type="button"
                        onClick={() => setComboSearch("")}
                        className="text-muted-foreground hover:text-foreground"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </div>

                  <div className="max-h-64 overflow-y-auto">
                    {fileGroups.length === 0 && (
                      <p className="px-4 py-6 text-center text-sm text-subtle">Ничего не найдено</p>
                    )}
                    {fileGroups.map(([folder, items]) => (
                      <div key={folder || "_root"}>
                        {folder && (
                          <div className="sticky top-0 bg-muted/80 px-3 py-1.5 backdrop-blur-sm">
                            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                              {folder}/
                            </span>
                          </div>
                        )}
                        {items.map((f) => (
                          <button
                            key={f.path}
                            type="button"
                            onClick={() => {
                              setSelectedPlaybook(f.path);
                              setComboOpen(false);
                              setComboSearch("");
                            }}
                            className={`flex w-full flex-col items-start px-4 py-2.5 text-left transition-colors hover:bg-muted ${
                              f.path === selectedPlaybook
                                ? "bg-blue-50 dark:bg-blue-950/30"
                                : ""
                            }`}
                          >
                            <span
                              className={`text-sm font-medium ${
                                f.path === selectedPlaybook
                                  ? "text-blue-700 dark:text-blue-300"
                                  : "text-foreground"
                              }`}
                            >
                              {f.display_name || prettyName(f.path)}
                            </span>
                            <span className="mt-0.5 font-mono text-xs text-subtle">{f.name}</span>
                          </button>
                        ))}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Host selection */}
        {selectedRepoId && (
          <div>
            <label className="field-label">Хосты</label>
            <div className="flex flex-wrap gap-2">
              <select
                value={selectedGroupId}
                onChange={(e) => setSelectedGroupId(e.target.value)}
                className="input-base w-auto py-1.5 text-xs"
              >
                <option value="">Выбрать по одному</option>
                {groups.map((g) => (
                  <option key={g.id} value={g.id}>{g.name}</option>
                ))}
              </select>
              {!selectedGroupId &&
                hosts.map((h) => (
                  <label
                    key={h.id}
                    className={selectedHostIds.includes(h.id) ? "chip-on" : "chip-off"}
                  >
                    <input
                      type="checkbox"
                      className="sr-only"
                      checked={selectedHostIds.includes(h.id)}
                      onChange={() => toggleHost(h.id)}
                    />
                    {h.hostname}
                  </label>
                ))}
            </div>
          </div>
        )}

        {/* Extra vars */}
        {selectedRepoId && (
          <div>
            <label className="field-label">Extra variables</label>
            <div className="space-y-2">
              {extraVars.map((pair, i) => (
                <div key={i} className="flex gap-2">
                  <input
                    placeholder="key"
                    value={pair.key}
                    onChange={(e) => updateExtraVar(i, "key", e.target.value)}
                    className="input-base w-1/3 py-1.5 text-sm font-mono"
                  />
                  <input
                    placeholder="value"
                    value={pair.value}
                    onChange={(e) => updateExtraVar(i, "value", e.target.value)}
                    className="input-base flex-1 py-1.5 text-sm"
                  />
                </div>
              ))}
              <button
                type="button"
                onClick={() => setExtraVars((prev) => [...prev, { key: "", value: "" }])}
                className="text-xs text-blue-600 transition-colors hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
              >
                + добавить переменную
              </button>
            </div>
          </div>
        )}

        {/* Actions */}
        {canEdit && selectedRepoId && (
          <div className="flex flex-wrap items-center gap-3 border-t border-border pt-4">
            <Button onClick={handleRun} disabled={!canRun}>
              <Play className="h-3.5 w-3.5" />
              Запустить сейчас
            </Button>
            <div className="flex items-center gap-2">
              <input
                value={cronExpression}
                onChange={(e) => setCronExpression(e.target.value)}
                className="input-base w-32 py-1.5 text-xs font-mono"
                placeholder="0 3 * * *"
              />
              <Button variant="secondary" onClick={handleCreateSchedule} disabled={!canRun}>
                По расписанию
              </Button>
            </div>
          </div>
        )}

        {runMessage && (
          <p className="animate-fade-in rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-400">
            {runMessage}
          </p>
        )}
      </div>

      {/* Schedules */}
      <div>
        <h2 className="mb-3 text-sm font-semibold text-foreground">Расписания</h2>
        <div className="table-shell">
          <table className="table-base">
            <thead>
              <tr>
                <th>Плейбук</th>
                <th>Репозиторий</th>
                <th>Cron</th>
                <th>Статус</th>
                {canEdit && <th className="text-right">Действия</th>}
              </tr>
            </thead>
            <tbody>
              {schedules.map((s) => (
                <tr key={s.id} className="is-interactive">
                  <td>
                    <div className="font-medium text-foreground">{prettyName(s.playbook_name)}</div>
                    <div className="mt-0.5 font-mono text-xs text-subtle">{s.playbook_name}</div>
                  </td>
                  <td className="text-muted-foreground">{repoName(s.repo_id)}</td>
                  <td className="font-mono text-sm text-muted-foreground">{s.cron_expression}</td>
                  <td>
                    <Badge status={s.enabled ? "success" : "disabled"}>
                      {s.enabled ? "включено" : "выключено"}
                    </Badge>
                  </td>
                  {canEdit && (
                    <td className="text-right">
                      <button onClick={() => handleDeleteSchedule(s.id)} className="action-danger">
                        <Trash2 className="h-3.5 w-3.5" />
                        Удалить
                      </button>
                    </td>
                  )}
                </tr>
              ))}
              {schedules.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-subtle">
                    Расписаний нет
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
