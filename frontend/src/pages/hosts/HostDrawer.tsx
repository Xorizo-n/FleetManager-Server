import { ReactNode, useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Activity, ArrowUpCircle, KeyRound, Monitor, Play, Power, Trash2 } from "lucide-react";
import { apiClient } from "../../api/client";
import { keys, useAlerts, useCanEdit, useCredentials, useFleet, useHostSoftware, useTasks } from "../../api/queries";
import type { AgentAlert, Host, NetworkAdapter, TaskRun } from "../../api/types";
import Drawer from "../../components/ui/Drawer";
import Tabs from "../../components/ui/Tabs";
import Button from "../../components/ui/Button";
import Badge from "../../components/ui/Badge";
import Checkbox from "../../components/ui/Checkbox";
import SearchInput from "../../components/ui/SearchInput";
import { Empty, ErrorText, Loading } from "../../components/ui/States";
import { useToast } from "../../components/ui/Toast";
import { useOpenTask } from "../../components/TaskPanel";
import { useAccessChange } from "../../components/useAccessChange";
import { AgentCell, StatusDot } from "./HostTable";
import { apiError, formatDateTime, formatRam, hostLabel, osLabel, relativeTime, STATUS_LABELS, taskTitle } from "../../lib/format";
import { isSystemSoftware } from "../../lib/software";
import { downloadRdpFile, rdpAddress } from "../../lib/rdp";
import { formatLinkSpeed, isSlowWiredLink, primaryAdapter } from "../../lib/hardware";
import { DiskList } from "../../components/DiskUsage";
import { ActivationSection } from "../../components/Activation";
import { sameCmidCount } from "../../lib/activation";
import { effectiveCredential, EffectiveCredential, isSshAssignable } from "../../lib/credentials";

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
  const alerts = useAlerts(host.id);

  async function diagnose() {
    try {
      const { data } = await apiClient.post(`/hosts/${host.id}/diagnostics`);
      openTask(data.id);
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось запустить диагностику") });
    }
  }

  async function wake() {
    try {
      const { data } = await apiClient.post<TaskRun>("/hosts/wake", { host_ids: [host.id] });
      openTask(data.id);
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось запустить пробуждение") });
    }
  }

  async function updateAgent() {
    if (!window.confirm(`Обновить агент на ${hostLabel(host)}?`)) return;
    try {
      const { data } = await apiClient.post<TaskRun>("/agent/update", { host_ids: [host.id] });
      if (data.status === "waiting") toast({ tone: "info", message: "ПК не в сети — агент обновится, когда он появится" });
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
      <div className="mb-4 flex flex-wrap gap-2">
        {canEdit && (
          <>
            <Button size="sm" onClick={() => onRunPlaybook([host.id])}>
              <Play className="h-3.5 w-3.5" />
              Запустить плейбук
            </Button>
            <Button size="sm" variant="secondary" onClick={diagnose}>
              <Activity className="h-3.5 w-3.5" />
              Диагностика
            </Button>
            {host.status !== "online" && (
              <Button
                size="sm"
                variant="secondary"
                onClick={wake}
                disabled={!host.hw_mac_address}
                title={
                  host.hw_mac_address
                    ? `Магический пакет на ${host.hw_mac_address} через включённый ПК той же подсети`
                    : "MAC-адрес неизвестен: агент сообщит его после обновления до 2026.10.12 и следующего включения"
                }
              >
                <Power className="h-3.5 w-3.5" />
                Разбудить
              </Button>
            )}
            {host.has_agent && (
              <Button size="sm" variant="secondary" onClick={updateAgent}>
                <ArrowUpCircle className="h-3.5 w-3.5" />
                Обновить агент
              </Button>
            )}
          </>
        )}
        {rdpAddress(host) && (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => downloadRdpFile(host)}
            title={`Скачать файл подключения к ${rdpAddress(host)}: откроется окно «Подключение к удалённому рабочему столу», логин и пароль — свои`}
          >
            <Monitor className="h-3.5 w-3.5" />
            RDP
          </Button>
        )}
        {canEdit && (
          <Button size="sm" variant="ghost" className="ml-auto text-rose-600 dark:text-rose-400" onClick={remove}>
            <Trash2 className="h-3.5 w-3.5" />
            Удалить
          </Button>
        )}
      </div>
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "overview", label: "Обзор" },
          { id: "software", label: "ПО" },
          { id: "tasks", label: "Задачи" },
          { id: "alerts", label: "Алерты", count: alerts.data?.length || undefined },
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
  const { hosts, tree, versionOf, agentVersions } = useFleet();
  const credentials = useCredentials();
  const sameCmid = useMemo(() => sameCmidCount(host.license_activation, hosts), [host.license_activation, hosts]);
  const runAccessChange = useAccessChange();
  const [form, setForm] = useState({ group_id: host.group_id ?? "", credential_id: host.credential_id ?? "", comment: host.comment ?? "" });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setForm({ group_id: host.group_id ?? "", credential_id: host.credential_id ?? "", comment: host.comment ?? "" });
  }, [host.id, host.group_id, host.credential_id, host.comment]);

  const dirty = form.group_id !== (host.group_id ?? "") || form.credential_id !== (host.credential_id ?? "") || form.comment !== (host.comment ?? "");

  const credentialName = (id: string) => credentials.data?.find((c) => c.id === id)?.name ?? "учётка";
  // Чем сервер подключается сейчас и чем будет подключаться после сохранения
  const current = effectiveCredential(host, tree, credentials.data);
  const next = effectiveCredential({ credential_id: form.credential_id || null, group_id: form.group_id || null }, tree, credentials.data);
  const usesAgentKey = current.source === "agent";
  const credentialChanges = dirty && (current.source !== next.source || ("credentialId" in current ? current.credentialId : null) !== ("credentialId" in next ? next.credentialId : null));
  const inheritedFromGroup = effectiveCredential({ credential_id: null, group_id: form.group_id || null }, tree, credentials.data);
  const credentialOptions = useMemo(() => (credentials.data ?? []).filter(isSshAssignable), [credentials.data]);

  const groupChanged = form.group_id !== (host.group_id ?? "");
  const credentialChanged = form.credential_id !== (host.credential_id ?? "");
  // Каждая смена доступа проверяется входом на ПК отдельно — группа и учётка сохраняются по очереди
  const bothAccessChanges = groupChanged && credentialChanged;

  async function save() {
    setSaving(true);
    setError(null);
    try {
      if (form.comment !== (host.comment ?? "")) {
        await apiClient.patch(`/hosts/${host.id}`, { comment: form.comment.trim() || null });
        await queryClient.invalidateQueries({ queryKey: keys.hosts });
        if (!groupChanged && !credentialChanged) toast({ tone: "success", message: "Комментарий сохранён" });
      }
      if (groupChanged) {
        await runAccessChange({ action: "move_to_group", host_ids: [host.id], group_id: form.group_id || null });
      } else if (credentialChanged) {
        await runAccessChange({ action: "set_host_credential", host_ids: [host.id], credential_id: form.credential_id || null });
      }
    } catch (err) {
      setError(apiError(err, "Не удалось сохранить хост"));
    } finally {
      setSaving(false);
    }
  }

  const describe = (e: EffectiveCredential) =>
    e.source === "agent"
      ? "ключ агента (выпущен при регистрации)"
      : e.source === "own"
        ? credentialName(e.credentialId)
        : e.source === "group"
          ? `${credentialName(e.credentialId)} — от группы ${e.groupPath}`
          : "учётные данные не заданы";

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
            <Field label="MAC-адрес">{host.hw_mac_address && <span className="font-mono">{host.hw_mac_address}</span>}</Field>
            <Field label="Процессор">{host.hw_processor}</Field>
            <Field label="Память">{formatRam(host.hw_total_memory_bytes)}</Field>
            <Field label="Скорость сети"><LinkSpeed adapter={primaryAdapter(host)} /></Field>
          </dl>
        ) : (
          <p className="text-sm text-subtle">Агент ещё не прислал данные об оборудовании</p>
        )}
      </section>

      {!!host.hw_disks?.length && (
        <section>
          <h3 className="mb-2 text-sm font-semibold text-foreground">Диски</h3>
          <DiskList disks={host.hw_disks} />
        </section>
      )}

      {(host.has_agent || host.license_activation) && (
        <section>
          <h3 className="mb-2 text-sm font-semibold text-foreground">Активация Windows и Office</h3>
          <ActivationSection host={host} sameCmid={sameCmid} />
        </section>
      )}

      {!!host.hw_network_adapters?.length && (
        <section>
          <h3 className="mb-2 text-sm font-semibold text-foreground">Сетевые адаптеры</h3>
          <NetworkAdapters host={host} />
        </section>
      )}

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
            {usesAgentKey ? (
              <>
                <div className="input-base flex items-center gap-2 bg-muted/40 text-muted-foreground">
                  <KeyRound className="h-3.5 w-3.5 shrink-0" />
                  Ключ агента (выпущен при регистрации)
                </div>
                <p className="mt-1 text-xs text-subtle">Ключ привязан к агенту на этом ПК и не меняется вручную; учётка группы на ПК с агентом не действует.</p>
              </>
            ) : (
              <select id="host-cred" disabled={!canEdit} value={form.credential_id} onChange={(e) => setForm({ ...form, credential_id: e.target.value })} className="input-base">
                <option value="">
                  {inheritedFromGroup.source === "group" ? `Как у группы: ${credentialName(inheritedFromGroup.credentialId)}` : "Не заданы (у группы тоже нет)"}
                </option>
                {credentialOptions.map((c) => <option key={c.id} value={c.id}>{c.name} · {c.login}</option>)}
              </select>
            )}
          </div>
          <div className="sm:col-span-2 rounded-lg border border-border bg-muted/30 px-3 py-2 text-sm">
            <span className="text-muted-foreground">Подключение по SSH: </span>
            <span className="text-foreground">{describe(current)}</span>
            {credentialChanges && (
              <span className={next.source === "none" ? "text-rose-600 dark:text-rose-400" : "text-amber-600 dark:text-amber-400"}>
                {" → после сохранения: "}
                {describe(next)}
                {next.source === "none" && " — SSH-подключение к ПК перестанет работать"}
              </span>
            )}
          </div>
          <div className="sm:col-span-2">
            <label className="field-label" htmlFor="host-comment">Комментарий</label>
            <textarea id="host-comment" disabled={!canEdit} rows={2} value={form.comment} onChange={(e) => setForm({ ...form, comment: e.target.value })} className="input-base" />
          </div>
        </div>
        {canEdit && (
          <div className="flex items-center gap-3">
            <Button size="sm" onClick={save} loading={saving} disabled={!dirty || bothAccessChanges}>
              {credentialChanges ? "Проверить вход и сохранить" : "Сохранить"}
            </Button>
            {dirty && (
              <button className="text-xs text-muted-foreground hover:text-foreground" onClick={() => setForm({ group_id: host.group_id ?? "", credential_id: host.credential_id ?? "", comment: host.comment ?? "" })}>
                Отменить изменения
              </button>
            )}
            <ErrorText>{error}</ErrorText>
          </div>
        )}
        {canEdit && bothAccessChanges && (
          <p className="text-xs text-amber-600 dark:text-amber-400">Группа и учётка проверяются входом на ПК по отдельности: сохраните сначала одно, потом другое.</p>
        )}
        {canEdit && credentialChanges && !bothAccessChanges && (
          <p className="text-xs text-subtle">Сервер сначала войдёт на ПК новыми данными; если вход не пройдёт, изменение не применится.</p>
        )}
      </section>
    </div>
  );
}

function LinkSpeed({ adapter }: { adapter: NetworkAdapter | null }) {
  const speed = formatLinkSpeed(adapter?.link_speed_bps);
  if (!speed) return null;
  return isSlowWiredLink(adapter) ? (
    <span className="text-amber-600 dark:text-amber-400" title="Проводной адаптер договорился с портом меньше чем на гигабит — проверьте кабель, патч-корд и порт коммутатора">
      {speed}
    </span>
  ) : (
    <>{speed}</>
  );
}

function NetworkAdapters({ host }: { host: Host }) {
  const adapters = [...(host.hw_network_adapters ?? [])].sort((a, b) => Number((b.status ?? "").toLowerCase() === "up") - Number((a.status ?? "").toLowerCase() === "up"));
  return (
    <ul className="divide-y divide-border rounded-lg border border-border">
      {adapters.map((a) => {
        const up = (a.status ?? "").toLowerCase() === "up";
        return (
          <li key={a.mac_address ?? a.name} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 px-3 py-2 text-sm">
            <span className={`h-2 w-2 shrink-0 self-center rounded-full ${up ? "bg-emerald-500" : "bg-slate-400"}`} title={a.status ?? undefined} />
            <span className="min-w-0 flex-1">
              <span className="font-medium text-foreground">{a.name ?? "Адаптер"}</span>
              {a.mac_address === host.hw_mac_address && <span className="text-xs text-subtle"> · связь с сервером</span>}
              {a.description && <span className="block truncate text-xs text-muted-foreground" title={a.description}>{a.description}</span>}
            </span>
            <span className="text-xs tabular-nums">{!up ? <span className="text-muted-foreground">нет линка</span> : a.link_speed_bps ? <LinkSpeed adapter={a} /> : "—"}</span>
            <span className="w-full pl-5 font-mono text-xs text-muted-foreground">
              {a.mac_address}
              {a.ipv4.length > 0 && ` · ${a.ipv4.join(", ")}`}
            </span>
          </li>
        );
      })}
    </ul>
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

const ALERT_TYPE_LABELS: Record<string, string> = { hardware_changed: "Смена оборудования" };

// До определения смены железа сервером агент присылал только хэши отпечатков
const isLegacyHardwareAlert = (a: AgentAlert) => a.alert_type === "hardware_changed" && a.message.startsWith("Hardware fingerprint changed");

function HostAlerts({ hostId }: { hostId: string }) {
  const { data, isLoading } = useAlerts(hostId);
  if (isLoading) return <Loading />;
  if (!data?.length) return <Empty>Алертов от агента нет</Empty>;
  return (
    <ul className="space-y-2">
      {data.map((a) => (
        <li key={a.id} className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-sm">
          <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
            <span>{ALERT_TYPE_LABELS[a.alert_type] ?? a.alert_type}</span>
            <span>{formatDateTime(a.created_at)}</span>
          </div>
          {isLegacyHardwareAlert(a) ? (
            <p className="mt-1 text-muted-foreground">
              Изменился отпечаток железа — алерт старого формата, без подробностей о том, что изменилось
            </p>
          ) : (
            <ul className="mt-1 space-y-0.5 text-foreground">
              {a.message.split("; ").map((part) => <li key={part}>{part}</li>)}
            </ul>
          )}
        </li>
      ))}
    </ul>
  );
}
