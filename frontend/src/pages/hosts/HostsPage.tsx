import { useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  Activity, ArrowUpCircle, ChevronDown, Download, FolderInput, KeyRound, MoreHorizontal, Play, Plus, RefreshCw, ScanLine, Trash2, Upload, X, XCircle,
} from "lucide-react";
import { apiClient } from "../../api/client";
import { keys, useAlertSummary, useCanEdit, useFleet } from "../../api/queries";
import type { Host } from "../../api/types";
import PageHeader from "../../components/ui/PageHeader";
import Button from "../../components/ui/Button";
import Menu from "../../components/ui/Menu";
import Modal from "../../components/ui/Modal";
import SearchInput from "../../components/ui/SearchInput";
import { Empty, Loading } from "../../components/ui/States";
import { useToast } from "../../components/ui/Toast";
import { useOpenTask } from "../../components/TaskPanel";
import PlaybookRunForm from "../../components/PlaybookRunForm";
import GroupSidebar from "./GroupSidebar";
import HostTable, { ColumnSet } from "./HostTable";
import HostDrawer from "./HostDrawer";
import { AddHostDialog, CredentialDialog, GroupDialog } from "./dialogs";
import { AGENT_FILTERS, ALERT_FILTERS, alertDays, CHECKED_FILTERS, filterHosts, useHostFilters } from "./filters";
import { downloadFromApi } from "../../lib/download";
import { apiError, OS_OPTIONS, osLabel, pcCount } from "../../lib/format";

const VIEW_KEY = "fm.hosts.view";

function readView(): { columns: ColumnSet; grouped: boolean } {
  try {
    return { columns: "main", grouped: true, ...JSON.parse(localStorage.getItem(VIEW_KEY) ?? "{}") };
  } catch {
    return { columns: "main", grouped: true };
  }
}

export default function HostsPage() {
  const canEdit = useCanEdit();
  const queryClient = useQueryClient();
  const toast = useToast();
  const openTask = useOpenTask();
  const { hosts, tree, hostById, versionOf, agentVersions, isLoading } = useFleet();
  const { filters, setFilter, reset, activeCount } = useHostFilters();
  const [params, setParams] = useSearchParams();
  const [view, setView] = useState(readView);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [runFor, setRunFor] = useState<string[] | null>(null);
  const [groupFor, setGroupFor] = useState<string[] | null>(null);
  const [credentialFor, setCredentialFor] = useState<string[] | null>(null);
  const [adding, setAdding] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  // Значок у ПК и фильтр «Алерты» — за выбранный в фильтре период, без фильтра — за неделю
  const alertSummary = useAlertSummary(alertDays(filters.alerts));
  const alertCounts = useMemo(() => new Map((alertSummary.data?.by_host ?? []).map((a) => [a.host_id, a.count])), [alertSummary.data]);
  const visible = useMemo(() => filterHosts(hosts, filters, tree, versionOf, alertCounts), [hosts, filters, tree, versionOf, alertCounts]);
  const openHost = params.get("host") ? hostById.get(params.get("host")!) : undefined;
  const stats = useMemo(() => ({ online: hosts.filter((h) => h.status === "online").length }), [hosts]);
  const selectedHosts = useMemo(() => [...selected].map((id) => hostById.get(id)).filter((h): h is Host => !!h), [selected, hostById]);
  const visibleIds = useMemo(() => new Set(visible.map((h) => h.id)), [visible]);
  const hiddenSelected = selectedHosts.filter((h) => !visibleIds.has(h.id)).length;
  const withAgent = selectedHosts.filter((h) => h.has_agent).map((h) => h.id);

  function updateView(next: Partial<typeof view>) {
    const merged = { ...view, ...next };
    setView(merged);
    try {
      localStorage.setItem(VIEW_KEY, JSON.stringify(merged));
    } catch {
      // вид таблицы просто не запомнится
    }
  }

  function setHostParam(id: string | null) {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (id) next.set("host", id);
      else next.delete("host");
      return next;
    });
  }

  function toggle(ids: string[]) {
    setSelected((prev) => {
      const next = new Set(prev);
      const all = ids.every((id) => next.has(id));
      ids.forEach((id) => (all ? next.delete(id) : next.add(id)));
      return next;
    });
  }

  async function startTask(request: Promise<{ data: { id?: string; task_run_id?: string } }>, fallback: string) {
    try {
      const { data } = await request;
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      openTask((data.id ?? data.task_run_id)!);
    } catch (err) {
      toast({ tone: "error", message: apiError(err, fallback) });
    }
  }

  async function bulkDelete() {
    if (!window.confirm(`Удалить из реестра ${pcCount(selected.size)}? Агенты на этих ПК зарегистрируются заново при следующем heartbeat.`)) return;
    try {
      const { data } = await apiClient.post<{ deleted: number }>("/hosts/delete", { host_ids: [...selected] });
      setSelected(new Set());
      queryClient.invalidateQueries({ queryKey: keys.hosts });
      toast({ tone: "success", message: `Удалено: ${pcCount(data.deleted)}` });
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось удалить хосты") });
    }
  }

  async function importCsv(file: File | undefined) {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    try {
      const { data } = await apiClient.post("/hosts/import-csv", form);
      queryClient.invalidateQueries({ queryKey: keys.hosts });
      toast({
        tone: data.errors?.length ? "error" : "success",
        message: `Импорт: создано ${data.created}, пропущено ${data.skipped}${data.errors?.length ? `, ошибок ${data.errors.length}: ${data.errors[0]}` : ""}`,
      });
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось импортировать CSV") });
    } finally {
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  const outdated = agentVersions?.outdated ?? 0;

  return (
    <div className="animate-fade-in space-y-4 pb-20">
      <PageHeader
        title="Хосты"
        description={
          <>
            {pcCount(hosts.length)} · <span className="text-emerald-600 dark:text-emerald-400">{stats.online} online</span>
            {outdated > 0 && (
              <>
                {" · "}
                <button className="text-amber-600 hover:underline dark:text-amber-400" onClick={() => setFilter("agent", "outdated")}>
                  устаревший агент на {pcCount(outdated)}
                </button>
              </>
            )}
            {agentVersions?.available_version && <span className="text-subtle"> · актуальная версия агента {agentVersions.available_version}</span>}
          </>
        }
        actions={
          <>
            {canEdit && (
              <Button size="sm" onClick={() => setAdding(true)}>
                <Plus className="h-3.5 w-3.5" />
                Добавить хост
              </Button>
            )}
            <Menu
              trigger={({ toggle }) => (
                <button className="btn-secondary btn-sm" onClick={toggle} aria-label="Другие действия">
                  <MoreHorizontal className="h-4 w-4" />
                </button>
              )}
              items={[
                ...(canEdit
                  ? [
                      { label: "Импорт из CSV", icon: <Upload className="h-4 w-4" />, onClick: () => fileRef.current?.click() },
                      {
                        label: "Проверить версии агента на всех",
                        icon: <RefreshCw className="h-4 w-4" />,
                        onClick: () => startTask(apiClient.post("/agent/version-scan", { host_ids: [] }), "Не удалось запустить проверку"),
                      },
                    ]
                  : []),
                { label: "Скачать inventory Ansible", icon: <Download className="h-4 w-4" />, onClick: () => downloadFromApi("/hosts/inventory", "inventory.ini") },
              ]}
            />
            <input ref={fileRef} type="file" accept=".csv" className="hidden" onChange={(e) => importCsv(e.target.files?.[0])} />
          </>
        }
      />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[15rem_minmax(0,1fr)]">
        <aside className="hidden xl:block">
          <div className="sticky top-[73px] max-h-[calc(100vh-90px)] overflow-y-auto pr-1">
            {!isLoading && <GroupSidebar tree={tree} total={hosts.length} online={stats.online} value={filters.group} onChange={(id) => setFilter("group", id)} />}
          </div>
        </aside>

        <div className="min-w-0 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <SearchInput value={filters.q} onChange={(v) => setFilter("q", v)} placeholder="Имя, IP, серийный номер, комментарий" className="min-w-[220px] flex-1" />
            <select value={filters.group} onChange={(e) => setFilter("group", e.target.value)} className="input-base w-auto max-w-[14rem] py-2 xl:hidden" aria-label="Группа">
              <option value="">Все группы</option>
              {tree.options.map((g) => <option key={g.id} value={g.id}>{g.label}</option>)}
            </select>
            <select value={filters.status} onChange={(e) => setFilter("status", e.target.value)} className="input-base w-auto py-2" aria-label="Статус">
              <option value="">Статус</option>
              <option value="online">online</option>
              <option value="offline">offline</option>
              <option value="unknown">неизвестно</option>
            </select>
            <select value={filters.agent} onChange={(e) => setFilter("agent", e.target.value)} className="input-base w-auto py-2" aria-label="Агент">
              <option value="">Агент</option>
              {AGENT_FILTERS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <select value={filters.os} onChange={(e) => setFilter("os", e.target.value)} className="input-base w-auto py-2" aria-label="ОС">
              <option value="">ОС</option>
              {OS_OPTIONS.map((o) => <option key={o} value={o}>{osLabel(o)}</option>)}
            </select>
            <select value={filters.checked} onChange={(e) => setFilter("checked", e.target.value)} className="input-base w-auto py-2" aria-label="Проверен">
              <option value="">Проверен</option>
              {CHECKED_FILTERS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <select value={filters.alerts} onChange={(e) => setFilter("alerts", e.target.value)} className="input-base w-auto py-2" aria-label="Алерты">
              <option value="">Алерты</option>
              {ALERT_FILTERS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            {(activeCount > 0 || filters.group) && (
              <button className="btn-ghost btn-sm" onClick={reset}>
                <XCircle className="h-3.5 w-3.5" />
                Сбросить
              </button>
            )}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <span className="text-muted-foreground">
              {visible.length === hosts.length ? `Все ${pcCount(hosts.length)}` : `Найдено ${pcCount(visible.length)} из ${hosts.length}`}
              {filters.group && <> в группе <b className="font-medium text-foreground">{tree.pathOf(filters.group)}</b></>}
            </span>
            <div className="flex items-center gap-3">
              <label className="flex cursor-pointer items-center gap-2 text-muted-foreground">
                <input type="checkbox" className="accent-blue-600" checked={view.grouped} onChange={(e) => updateView({ grouped: e.target.checked })} />
                По аудиториям
              </label>
              <div className="inline-flex rounded-lg border border-border bg-muted/40 p-0.5" role="radiogroup" aria-label="Колонки">
                {(["main", "hardware"] as const).map((c) => (
                  <button
                    key={c}
                    role="radio"
                    aria-checked={view.columns === c}
                    onClick={() => updateView({ columns: c })}
                    className={`rounded-md px-2.5 py-1 text-xs font-medium ${view.columns === c ? "bg-surface text-foreground shadow-panel" : "text-muted-foreground hover:text-foreground"}`}
                  >
                    {c === "main" ? "Основное" : "Железо"}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {isLoading ? (
            <Loading label="Загрузка реестра…" />
          ) : visible.length === 0 ? (
            <div className="rounded-xl border border-border bg-surface">
              <Empty>{hosts.length === 0 ? "Хостов нет — установите агент на ПК или добавьте хост вручную" : "Ничего не найдено по заданным фильтрам"}</Empty>
            </div>
          ) : (
            <HostTable
              hosts={visible}
              tree={tree}
              versionOf={versionOf}
              columns={view.columns}
              grouped={view.grouped}
              selectable={canEdit}
              selected={selected}
              onToggle={toggle}
              onOpen={(h) => setHostParam(h.id)}
              alertCounts={alertCounts}
            />
          )}
        </div>
      </div>

      {canEdit && selected.size > 0 && (
        <div className="fixed inset-x-0 bottom-4 z-30 flex justify-center px-4">
          <div className="flex max-w-full animate-slide-up flex-wrap items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2 shadow-panel-lg">
            <span className="px-1 text-sm font-medium text-foreground">
              Выбрано {pcCount(selected.size)}
              {hiddenSelected > 0 && <span className="font-normal text-muted-foreground"> ({hiddenSelected} скрыто фильтром)</span>}
            </span>
            <Button size="sm" onClick={() => setRunFor([...selected])}>
              <Play className="h-3.5 w-3.5" />
              Запустить плейбук
            </Button>
            <Button size="sm" variant="secondary" onClick={() => startTask(apiClient.post("/software/scan", { host_ids: [...selected] }), "Не удалось запустить сканирование")}>
              <ScanLine className="h-3.5 w-3.5" />
              Сканировать ПО
            </Button>
            <Menu
              direction="up"
              trigger={({ toggle }) => (
                <Button size="sm" variant="secondary" onClick={toggle}>
                  Ещё
                  <ChevronDown className="h-3.5 w-3.5" />
                </Button>
              )}
              items={[
                {
                  label: "Диагностика подключения",
                  icon: <Activity className="h-4 w-4" />,
                  disabled: selected.size !== 1,
                  hint: "Диагностика запускается для одного хоста",
                  onClick: () => startTask(apiClient.post(`/hosts/${[...selected][0]}/diagnostics`), "Не удалось запустить диагностику"),
                },
                {
                  label: `Проверить версию агента (${withAgent.length})`,
                  icon: <RefreshCw className="h-4 w-4" />,
                  disabled: withAgent.length === 0,
                  onClick: () => startTask(apiClient.post("/agent/version-scan", { host_ids: withAgent }), "Не удалось запустить проверку"),
                },
                {
                  label: `Обновить агент (${withAgent.length})`,
                  icon: <ArrowUpCircle className="h-4 w-4" />,
                  disabled: withAgent.length === 0 || !agentVersions?.installer_present,
                  hint: agentVersions?.installer_present ? undefined : "Установщик агента ещё не синхронизирован",
                  onClick: () =>
                    window.confirm(`Обновить агент до ${agentVersions?.available_version ?? "последней версии"} на ${pcCount(withAgent.length)}?`) &&
                    startTask(apiClient.post("/agent/update", { host_ids: withAgent }), "Не удалось запустить обновление"),
                },
                "divider",
                { label: "Назначить группу…", icon: <FolderInput className="h-4 w-4" />, onClick: () => setGroupFor([...selected]) },
                { label: "Учётные данные SSH…", icon: <KeyRound className="h-4 w-4" />, onClick: () => setCredentialFor([...selected]) },
                { label: "Удалить из реестра", icon: <Trash2 className="h-4 w-4" />, danger: true, onClick: bulkDelete },
              ]}
            />
            <button className="btn-ghost btn-sm" onClick={() => setSelected(new Set())} aria-label="Снять выбор">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      {openHost && <HostDrawer host={openHost} onClose={() => setHostParam(null)} onRunPlaybook={(ids) => setRunFor(ids)} />}
      {runFor && (
        <Modal open onClose={() => setRunFor(null)} title="Запуск плейбука" size="lg">
          <PlaybookRunForm initialHostIds={runFor} onDone={() => setRunFor(null)} pickerHeight={280} />
        </Modal>
      )}
      {groupFor && <GroupDialog hostIds={groupFor} onClose={() => setGroupFor(null)} onDone={() => { setGroupFor(null); setSelected(new Set()); }} />}
      {credentialFor && <CredentialDialog hostIds={credentialFor} onClose={() => setCredentialFor(null)} onDone={() => { setCredentialFor(null); setSelected(new Set()); }} />}
      {adding && <AddHostDialog onClose={() => setAdding(false)} />}
    </div>
  );
}
