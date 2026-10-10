import { FormEvent, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { GitBranch, Pencil, Plus, RefreshCw, Trash2 } from "lucide-react";
import { apiClient } from "../api/client";
import { keys, useCredentials, useFleet, usePlaybookFiles, useRepos, useSchedules } from "../api/queries";
import type { Schedule } from "../api/types";
import PageHeader from "../components/ui/PageHeader";
import Tabs from "../components/ui/Tabs";
import Button from "../components/ui/Button";
import Modal from "../components/ui/Modal";
import Switch from "../components/ui/Switch";
import { Empty, ErrorText, Loading } from "../components/ui/States";
import { useToast } from "../components/ui/Toast";
import PlaybookRunForm from "../components/PlaybookRunForm";
import HostPicker from "../components/HostPicker";
import ExtraVarsEditor, { objectToVars, VarPair, varsToObject } from "../components/ExtraVarsEditor";
import { playbookLabel } from "../components/PlaybookSelect";
import { compactSelection, GroupTree } from "../lib/groupTree";
import { CRON_PRESETS, describeCron } from "../lib/cron";
import { apiError, formatDateTime, pcCount, playbookShortName } from "../lib/format";

type Tab = "run" | "schedules" | "repos";

export default function Automation() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "run";
  const schedules = useSchedules();
  const repos = useRepos();

  return (
    <div className="animate-fade-in space-y-5">
      <PageHeader title="Автоматизация" description="Запуск плейбуков Ansible на хостах и расписания" />
      <Tabs<Tab>
        value={tab}
        onChange={(id) => setParams((prev) => { const next = new URLSearchParams(prev); next.set("tab", id); return next; })}
        tabs={[
          { id: "run", label: "Запуск" },
          { id: "schedules", label: "Расписания", count: schedules.data?.length },
          { id: "repos", label: "Репозитории", count: repos.data?.length },
        ]}
      />
      {tab === "run" && (
        <div className="surface-panel max-w-4xl">
          <PlaybookRunForm key={params.get("mode") ?? "now"} initialMode={params.get("mode") === "schedule" ? "schedule" : "now"} pickerHeight={380} />
        </div>
      )}
      {tab === "schedules" && <SchedulesTab />}
      {tab === "repos" && <ReposTab />}
    </div>
  );
}

/** Хосты, на которые сейчас раскрывается расписание (группы — вместе с подгруппами). */
function scheduleHostIds(tree: GroupTree, schedule: Schedule) {
  const ids = new Set(schedule.host_ids);
  schedule.host_group_ids.forEach((g) => tree.byId.get(g)?.hostIds.forEach((id) => ids.add(id)));
  return ids;
}

function TargetsSummary({ tree, schedule }: { tree: GroupTree; schedule: Schedule }) {
  const total = scheduleHostIds(tree, schedule).size;
  const groups = schedule.host_group_ids.map((g) => tree.pathOf(g));
  return (
    <div className="min-w-0">
      <div className="truncate text-foreground" title={groups.join(", ")}>
        {groups.length > 0 ? groups.slice(0, 2).join(", ") + (groups.length > 2 ? ` и ещё ${groups.length - 2}` : "") : "Отдельные ПК"}
        {groups.length > 0 && schedule.host_ids.length > 0 && ` + ${pcCount(schedule.host_ids.length)}`}
      </div>
      <div className="text-xs text-muted-foreground">сейчас {pcCount(total)}</div>
    </div>
  );
}

function SchedulesTab() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { tree } = useFleet();
  const schedules = useSchedules();
  const repos = useRepos();
  const [editing, setEditing] = useState<Schedule | null>(null);
  const [, setParams] = useSearchParams();

  async function patch(schedule: Schedule, body: Partial<Schedule>) {
    try {
      await apiClient.patch(`/playbooks/schedules/${schedule.id}`, body);
      queryClient.invalidateQueries({ queryKey: keys.schedules });
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось изменить расписание") });
    }
  }

  async function remove(schedule: Schedule) {
    if (!window.confirm(`Удалить расписание «${playbookShortName(schedule.playbook_name)}»?`)) return;
    await apiClient.delete(`/playbooks/schedules/${schedule.id}`);
    queryClient.invalidateQueries({ queryKey: keys.schedules });
    toast({ tone: "success", message: "Расписание удалено" });
  }

  if (schedules.isLoading) return <Loading />;
  const list = schedules.data ?? [];

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <Button size="sm" onClick={() => setParams({ tab: "run", mode: "schedule" })}>
          <Plus className="h-3.5 w-3.5" />
          Новое расписание
        </Button>
      </div>
      <div className="table-shell">
        <table className="table-base">
          <thead>
            <tr>
              <th className="w-12">Вкл.</th>
              <th>Плейбук</th>
              <th>Цели</th>
              <th>Когда</th>
              <th>Следующий запуск</th>
              <th className="w-24" />
            </tr>
          </thead>
          <tbody>
            {list.map((s) => (
              <tr key={s.id} className={s.enabled ? "" : "opacity-60"}>
                <td>
                  <Switch checked={s.enabled} onChange={(enabled) => patch(s, { enabled })} label={s.enabled ? "Выключить расписание" : "Включить расписание"} />
                </td>
                <td>
                  <div className="font-medium text-foreground">{playbookShortName(s.playbook_name)}</div>
                  <div className="font-mono text-xs text-subtle">
                    {s.playbook_name}
                    {(repos.data?.length ?? 0) > 1 && ` · ${repos.data?.find((r) => r.id === s.repo_id)?.name}`}
                  </div>
                </td>
                <td className="max-w-[260px]">
                  <TargetsSummary tree={tree} schedule={s} />
                </td>
                <td>
                  <div className="text-foreground">{describeCron(s.cron_expression) ?? "по cron"}</div>
                  <div className="font-mono text-xs text-subtle">{s.cron_expression}</div>
                </td>
                <td className="text-muted-foreground">{s.next_run_at ? formatDateTime(s.next_run_at) : "выключено"}</td>
                <td className="text-right">
                  <div className="inline-flex gap-1">
                    <button className="action-icon" onClick={() => setEditing(s)} aria-label="Изменить расписание" title="Изменить">
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    <button className="action-danger" onClick={() => remove(s)} aria-label="Удалить расписание" title="Удалить">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {list.length === 0 && <Empty>Расписаний нет — создайте его на вкладке «Запуск», выбрав «По расписанию»</Empty>}
      </div>
      {editing && <ScheduleEditor schedule={editing} tree={tree} onClose={() => setEditing(null)} />}
    </div>
  );
}

function ScheduleEditor({ schedule, tree, onClose }: { schedule: Schedule; tree: GroupTree; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const files = usePlaybookFiles(schedule.repo_id);
  const [selection, setSelection] = useState(() => scheduleHostIds(tree, schedule));
  const [cron, setCron] = useState(schedule.cron_expression);
  const [vars, setVars] = useState<VarPair[]>(() => objectToVars(schedule.extra_vars));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const file = files.data?.find((f) => f.path === schedule.playbook_name);

  async function save() {
    const { groupIds, hostIds } = compactSelection(tree, selection);
    setBusy(true);
    setError(null);
    try {
      await apiClient.patch(`/playbooks/schedules/${schedule.id}`, {
        cron_expression: cron,
        host_group_ids: groupIds,
        host_ids: hostIds,
        extra_vars: varsToObject(vars),
      });
      queryClient.invalidateQueries({ queryKey: keys.schedules });
      toast({ tone: "success", message: "Расписание сохранено" });
      onClose();
    } catch (err) {
      setError(apiError(err, "Не удалось сохранить расписание"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title={`Расписание: ${file ? playbookLabel(file) : playbookShortName(schedule.playbook_name)}`}
      footer={
        <>
          <ErrorText>{error}</ErrorText>
          <Button variant="secondary" onClick={onClose}>Отмена</Button>
          <Button onClick={save} loading={busy} disabled={selection.size === 0}>Сохранить</Button>
        </>
      }
    >
      <div className="space-y-4">
        <div>
          <label className="field-label">Когда</label>
          <div className="flex flex-wrap items-center gap-2">
            {CRON_PRESETS.map((p) => (
              <button key={p.value} type="button" onClick={() => setCron(p.value)} className={cron === p.value ? "chip-on" : "chip-off"}>
                {p.label}
              </button>
            ))}
            <input value={cron} onChange={(e) => setCron(e.target.value)} className="input-base w-36 py-1 font-mono text-xs" aria-label="Cron-выражение" />
            <span className="text-xs text-muted-foreground">{describeCron(cron) ?? ""}</span>
          </div>
        </div>
        <div>
          <label className="field-label">Хосты</label>
          <HostPicker value={selection} onChange={setSelection} height={300} />
        </div>
        <div>
          <label className="field-label">Переменные</label>
          <ExtraVarsEditor value={vars} onChange={setVars} />
        </div>
      </div>
    </Modal>
  );
}

function ReposTab() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const repos = useRepos();
  const credentials = useCredentials();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: "", git_url: "", git_token: "", credential_id: "", branch: "main" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const sshKeys = useMemo(() => (credentials.data ?? []).filter((c) => c.type === "ssh_key" && !c.is_agent_managed), [credentials.data]);
  const isSsh = /^(git@|ssh:\/\/)/.test(form.git_url.trim());

  async function add(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy("add");
    try {
      await apiClient.post("/playbooks/repos", { ...form, credential_id: form.credential_id || null, git_token: form.git_token || null });
      setForm({ name: "", git_url: "", git_token: "", credential_id: "", branch: "main" });
      setShowForm(false);
      queryClient.invalidateQueries({ queryKey: keys.repos });
      toast({ tone: "success", message: "Репозиторий подключён" });
    } catch (err) {
      setError(apiError(err, "Не удалось подключить репозиторий"));
    } finally {
      setBusy(null);
    }
  }

  async function sync(id: string) {
    setBusy(id);
    try {
      await apiClient.post(`/playbooks/repos/${id}/sync`);
      queryClient.invalidateQueries({ queryKey: keys.files(id) });
      toast({ tone: "success", message: "Репозиторий обновлён" });
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось обновить репозиторий") });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <Button size="sm" variant={showForm ? "secondary" : "primary"} onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Отмена" : <><GitBranch className="h-3.5 w-3.5" />Подключить репозиторий</>}
        </Button>
      </div>
      {showForm && (
        <form onSubmit={add} className="surface-panel grid animate-slide-up grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label className="field-label">Название</label>
            <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="input-base" />
          </div>
          <div>
            <label className="field-label">Git URL</label>
            <input required placeholder="https://… или git@host:group/repo.git" value={form.git_url} onChange={(e) => setForm({ ...form, git_url: e.target.value })} className="input-base font-mono" />
          </div>
          {isSsh ? (
            <div>
              <label className="field-label">SSH-ключ из учётных данных</label>
              <select required value={form.credential_id} onChange={(e) => setForm({ ...form, credential_id: e.target.value })} className="input-base">
                <option value="">Выберите ключ</option>
                {sshKeys.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
          ) : (
            <div>
              <label className="field-label">Токен доступа (необязательно)</label>
              <input value={form.git_token} onChange={(e) => setForm({ ...form, git_token: e.target.value })} className="input-base" autoComplete="off" />
            </div>
          )}
          <div>
            <label className="field-label">Ветка</label>
            <input value={form.branch} onChange={(e) => setForm({ ...form, branch: e.target.value })} className="input-base" />
          </div>
          <div className="flex items-center gap-3 sm:col-span-2">
            <Button type="submit" loading={busy === "add"}>Подключить</Button>
            <ErrorText>{error}</ErrorText>
          </div>
        </form>
      )}
      <div className="table-shell">
        <table className="table-base">
          <thead>
            <tr>
              <th>Репозиторий</th>
              <th>Ветка</th>
              <th>Доступ</th>
              <th className="w-32" />
            </tr>
          </thead>
          <tbody>
            {(repos.data ?? []).map((r) => (
              <tr key={r.id}>
                <td>
                  <div className="font-medium text-foreground">{r.name}</div>
                  <div className="font-mono text-xs text-subtle">{r.git_url}</div>
                </td>
                <td className="font-mono text-sm">{r.branch}</td>
                <td className="text-muted-foreground">{r.credential_id ? credentials.data?.find((c) => c.id === r.credential_id)?.name ?? "SSH-ключ" : "HTTPS"}</td>
                <td className="text-right">
                  <Button size="sm" variant="secondary" onClick={() => sync(r.id)} loading={busy === r.id}>
                    {busy !== r.id && <RefreshCw className="h-3.5 w-3.5" />}
                    Обновить
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {repos.data?.length === 0 && <Empty>Репозитории не подключены</Empty>}
      </div>
    </div>
  );
}
