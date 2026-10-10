import { ReactNode, useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Activity, ArrowUpCircle, Play, Trash2 } from "lucide-react";
import { apiClient } from "../../api/client";
import { keys, useAlerts, useCanEdit, useCredentials, useFleet, useHostSoftware, useTasks } from "../../api/queries";
import type { Host } from "../../api/types";
import Drawer from "../../components/ui/Drawer";
import Tabs from "../../components/ui/Tabs";
import Button from "../../components/ui/Button";
import Badge from "../../components/ui/Badge";
import Checkbox from "../../components/ui/Checkbox";
import SearchInput from "../../components/ui/SearchInput";
import { Empty, ErrorText, Loading } from "../../components/ui/States";
import { useToast } from "../../components/ui/Toast";
import { useOpenTask } from "../../components/TaskPanel";
import { AgentCell, StatusDot } from "./HostTable";
import { apiError, formatDateTime, formatRam, hostLabel, osLabel, relativeTime, STATUS_LABELS, taskTitle } from "../../lib/format";
import { isSystemSoftware } from "../../lib/software";

type Tab = "overview" | "software" | "tasks" | "alerts";

interface Props {
  host: Host;
  onClose: () => void;
  onRunPlaybook: (hostIds: string[]) => void;
}

export default function HostDrawer({ host, onClose, onRunPlaybook }: Props) {
  const [tab, setTab] = useState<Tab>("overview");
  const canEdit = useCanEdit();
  const queryClient = useQueryClient();
  const toast = useToast();
  const openTask = useOpenTask();
  const { tree } = useFleet();

  async function diagnose() {
    try {
      const { data } = await apiClient.post(`/hosts/${host.id}/diagnostics`);
      openTask(data.id);
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось запустить диагностику") });
    }
  }

  async function updateAgent() {
    if (!window.confirm(`Обновить агент на ${hostLabel(host)}?`)) return;
    try {
      const { data } = await apiClient.post("/agent/update", { host_ids: [host.id] });
      openTask(data.id);
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось запустить обновление агента") });
    }
  }

  async function remove() {
    if (!window.confirm(`Удалить хост ${hostLabel(host)} из реестра?`)) return;
    try {
      await apiClient.delete(`/hosts/${host.id}`);
      queryClient.invalidateQueries({ queryKey: keys.hosts });
      toast({ tone: "success", message: `Хост ${hostLabel(host)} удалён` });
      onClose();
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось удалить хост") });
    }
  }

  return (
    <Drawer
      open
      onClose={onClose}
      width="lg"
      title={hostLabel(host)}
      subtitle={
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <StatusDot status={host.status} />
          <span className="font-mono text-xs">{host.ip_address ?? "—"}</span>
          <span>{tree.pathOf(host.group_id)}</span>
        </span>
      }
    >
      {canEdit && (
        <div className="mb-4 flex flex-wrap gap-2">
          <Button size="sm" onClick={() => onRunPlaybook([host.id])}>
            <Play className="h-3.5 w-3.5" />
            Запустить плейбук
          </Button>
          <Button size="sm" variant="secondary" onClick={diagnose}>
            <Activity className="h-3.5 w-3.5" />
            Диагностика
          </Button>
          {host.has_agent && (
            <Button size="sm" variant="secondary" onClick={updateAgent}>
              <ArrowUpCircle className="h-3.5 w-3.5" />
              Обновить агент
            </Button>
          )}
          <Button size="sm" variant="ghost" className="ml-auto text-rose-600 dark:text-rose-400" onClick={remove}>
            <Trash2 className="h-3.5 w-3.5" />
            Удалить
          </Button>
        </div>
      )}
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "overview", label: "Обзор" },
          { id: "software", label: "ПО" },
          { id: "tasks", label: "Задачи" },
          { id: "alerts", label: "Алерты" },
        ]}
      />
      <div className="pt-4">
        {tab === "overview" && <Overview host={host} />}
        {tab === "software" && <HostSoftware hostId={host.id} />}
        {tab === "tasks" && <HostTasks hostId={host.id} />}
        {tab === "alerts" && <HostAlerts hostId={host.id} />}
      </div>
    </Drawer>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 break-words text-sm text-foreground">{children || "—"}</dd>
    </div>
  );
}

function Overview({ host }: { host: Host }) {
  const canEdit = useCanEdit();
  const queryClient = useQueryClient();
  const toast = useToast();
  const { tree, versionOf, agentVersions } = useFleet();
  const credentials = useCredentials();
  const [form, setForm] = useState({ group_id: host.group_id ?? "", credential_id: host.credential_id ?? "", comment: host.comment ?? "" });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setForm({ group_id: host.group_id ?? "", credential_id: host.credential_id ?? "", comment: host.comment ?? "" });
  }, [host.id, host.group_id, host.credential_id, host.comment]);

  const dirty = form.group_id !== (host.group_id ?? "") || form.credential_id !== (host.credential_id ?? "") || form.comment !== (host.comment ?? "");

  // Учётка, которая действует, если у хоста своей нет: ближайшая вверх по дереву групп
  const inherited = useMemo(() => {
    let node = form.group_id ? tree.byId.get(form.group_id) : undefined;
    while (node?.group) {
      if (node.group.credential_id) return { group: node.path, credential: credentials.data?.find((c) => c.id === node!.group!.credential_id)?.name ?? "учётка группы" };
      node = node.group.parent_id ? tree.byId.get(node.group.parent_id) : undefined;
    }
    return null;
  }, [form.group_id, tree, credentials.data]);

  const credentialOptions = useMemo(() => {
    const list = credentials.data ?? [];
    // Служебный ключ агента показываем только свой, чтобы не листать тысячу чужих
    return list.filter((c) => !c.is_agent_managed || c.id === host.credential_id);
  }, [credentials.data, host.credential_id]);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await apiClient.patch(`/hosts/${host.id}`, {
        comment: form.comment.trim() || null,
        credential_id: form.credential_id || null,
      });
      if (form.group_id !== (host.group_id ?? "")) {
        if (form.group_id) await apiClient.post("/hosts/groups/assign", { host_ids: [host.id], group_id: form.group_id });
        else await apiClient.post("/hosts/groups/unassign", { host_ids: [host.id] });
      }
      await queryClient.invalidateQueries({ queryKey: keys.hosts });
      toast({ tone: "success", message: "Изменения сохранены" });
    } catch (err) {
      setError(apiError(err, "Не удалось сохранить хост"));
    } finally {
      setSaving(false);
    }
  }

  const usesAgentKey = !!credentials.data?.find((c) => c.id === host.credential_id)?.is_agent_managed;
  const status = versionOf(host);
  return (
    <div className="space-y-6">
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
        <Field label="ОС">{host.hw_os_caption || osLabel(host.os)}</Field>
        <Field label="Последний heartbeat">{host.has_agent ? relativeTime(host.last_seen_at) : "нет агента"}</Field>
        <Field label="Проверен">{relativeTime(host.last_checked_at)}</Field>
        <Field label="Агент">
          <AgentCell host={host} status={status} />
          {status === "outdated" && agentVersions?.available_version && <span className="text-xs text-subtle"> доступна {agentVersions.available_version}</span>}
        </Field>
        <Field label="Добавлен">{formatDateTime(host.created_at)}</Field>
      </dl>

      <section>
        <h3 className="mb-2 text-sm font-semibold text-foreground">Оборудование</h3>
        {host.hw_model || host.hw_processor ? (
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
            <Field label="Производитель">{host.hw_manufacturer}</Field>
            <Field label="Модель">{host.hw_model}</Field>
            <Field label="Серийный номер">{host.hw_serial_number}</Field>
            <Field label="Процессор">{host.hw_processor}</Field>
            <Field label="Память">{formatRam(host.hw_total_memory_bytes)}</Field>
          </dl>
        ) : (
          <p className="text-sm text-subtle">Агент ещё не прислал данные об оборудовании</p>
        )}
      </section>

      <section className="space-y-3">
        <h3 className="text-sm font-semibold text-foreground">Управление</h3>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label className="field-label" htmlFor="host-group">Группа</label>
            <select id="host-group" disabled={!canEdit} value={form.group_id} onChange={(e) => setForm({ ...form, group_id: e.target.value })} className="input-base">
              <option value="">Без группы</option>
              {tree.options.map((g) => <option key={g.id} value={g.id}>{g.label}</option>)}
            </select>
          </div>
          <div>
            <label className="field-label" htmlFor="host-cred">Учётные данные SSH</label>
            <select id="host-cred" disabled={!canEdit} value={form.credential_id} onChange={(e) => setForm({ ...form, credential_id: e.target.value })} className="input-base">
              <option value="">{inherited ? `Наследовать от группы (${inherited.credential})` : "Не заданы"}</option>
              {credentialOptions.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.is_agent_managed ? "Ключ агента (выпущен при регистрации)" : c.name}
                </option>
              ))}
            </select>
            {!form.credential_id && inherited && <p className="mt-1 text-xs text-subtle">Действует учётка группы {inherited.group}</p>}
            {usesAgentKey && form.credential_id !== host.credential_id && (
              <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">
                Хост перестанет использовать ключ, выпущенный агенту: SSH-доступ будет работать только с выбранной учёткой
              </p>
            )}
          </div>
          <div className="sm:col-span-2">
            <label className="field-label" htmlFor="host-comment">Комментарий</label>
            <textarea id="host-comment" disabled={!canEdit} rows={2} value={form.comment} onChange={(e) => setForm({ ...form, comment: e.target.value })} className="input-base" />
          </div>
        </div>
        {canEdit && (
          <div className="flex items-center gap-3">
            <Button size="sm" onClick={save} loading={saving} disabled={!dirty}>Сохранить</Button>
            {dirty && (
              <button className="text-xs text-muted-foreground hover:text-foreground" onClick={() => setForm({ group_id: host.group_id ?? "", credential_id: host.credential_id ?? "", comment: host.comment ?? "" })}>
                Отменить изменения
              </button>
            )}
            <ErrorText>{error}</ErrorText>
          </div>
        )}
      </section>
    </div>
  );
}

function HostSoftware({ hostId }: { hostId: string }) {
  const { data, isLoading } = useHostSoftware(hostId);
  const [search, setSearch] = useState("");
  const [hideSystem, setHideSystem] = useState(true);
  const items = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (data ?? [])
      .filter((s) => (!hideSystem || !isSystemSoftware(s.name)) && (!q || s.name.toLowerCase().includes(q)))
      .sort((a, b) => a.name.localeCompare(b.name, "ru"));
  }, [data, search, hideSystem]);

  if (isLoading) return <Loading />;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <SearchInput value={search} onChange={setSearch} placeholder="Поиск по названию" className="min-w-[200px] flex-1" />
        <label className="flex cursor-pointer items-center gap-2 text-sm text-muted-foreground">
          <Checkbox checked={hideSystem} onChange={(e) => setHideSystem(e.target.checked)} />
          Скрыть системное
        </label>
        <span className="text-xs text-muted-foreground">{items.length} из {data?.length ?? 0}</span>
      </div>
      <div className="table-shell">
        <table className="table-base">
          <thead>
            <tr>
              <th>Название</th>
              <th>Версия</th>
              <th>Источник</th>
              <th>Обнаружено</th>
            </tr>
          </thead>
          <tbody>
            {items.map((s) => (
              <tr key={s.id}>
                <td className="font-medium text-foreground">{s.name}</td>
                <td className="font-mono text-xs">{s.version ?? "—"}</td>
                <td className="text-muted-foreground">{s.install_method}</td>
                <td className="text-muted-foreground">{relativeTime(s.detected_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {items.length === 0 && <Empty>{data?.length ? "Ничего не найдено" : "Инвентаризация ПО ещё не поступала"}</Empty>}
      </div>
    </div>
  );
}

function HostTasks({ hostId }: { hostId: string }) {
  const { data, isLoading } = useTasks({ host_id: hostId, limit: 50 }, false);
  const openTask = useOpenTask();
  if (isLoading) return <Loading />;
  if (!data?.length) return <Empty>Задач с этим хостом не было</Empty>;
  return (
    <ul className="divide-y divide-border rounded-lg border border-border">
      {data.map((t) => (
        <li key={t.id}>
          <button className="flex w-full items-center gap-3 px-3 py-2.5 text-left text-sm hover:bg-muted/50" onClick={() => openTask(t.id)}>
            <span className="min-w-0 flex-1 truncate font-medium text-foreground">{taskTitle(t)}</span>
            <span className="shrink-0 text-xs text-muted-foreground">{t.created_by_name ?? ""}</span>
            <span className="shrink-0 text-xs text-muted-foreground">{formatDateTime(t.created_at)}</span>
            <Badge status={t.status}>{STATUS_LABELS[t.status]}</Badge>
          </button>
        </li>
      ))}
    </ul>
  );
}

function HostAlerts({ hostId }: { hostId: string }) {
  const { data, isLoading } = useAlerts(hostId);
  if (isLoading) return <Loading />;
  if (!data?.length) return <Empty>Алертов от агента нет</Empty>;
  return (
    <ul className="space-y-2">
      {data.map((a) => (
        <li key={a.id} className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-sm">
          <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
            <span className="font-mono">{a.alert_type}</span>
            <span>{formatDateTime(a.created_at)}</span>
          </div>
          <p className="mt-1 text-foreground">{a.message}</p>
        </li>
      ))}
    </ul>
  );
}
