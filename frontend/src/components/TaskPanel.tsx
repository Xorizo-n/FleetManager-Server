import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import Drawer from "./ui/Drawer";
import Badge from "./ui/Badge";
import Button from "./ui/Button";
import SearchInput from "./ui/SearchInput";
import { useToast } from "./ui/Toast";
import { Clock, RotateCcw, ScrollText, XCircle } from "lucide-react";
import { apiClient } from "../api/client";
import TaskLog from "./TaskLog";
import HostStateBar from "./HostStateBar";
import { Loading } from "./ui/States";
import { keys, useCanEdit, useFleet, useTask } from "../api/queries";
import { apiError, formatDateTime, formatDuration, hostLabel, pcCount, playbookShortName, STATUS_LABELS, TASK_TYPE_LABELS, taskTitle } from "../lib/format";
import { countHostStates, displayStatus, finishedCount, HOST_STATE_INFO, HOST_STATES, hostStateOf } from "../lib/hostStates";
import type { HostState, RunAs, TaskRun, TaskRunDetail } from "../api/types";

const TaskPanelContext = createContext<(taskId: string) => void>(() => {});

/** Открыть лог задачи с любой страницы: openTask(id). Задача пишется в ?task=, ссылкой можно поделиться. */
export const useOpenTask = () => useContext(TaskPanelContext);

export function TaskPanelProvider({ children }: { children: ReactNode }) {
  const [params, setParams] = useSearchParams();
  const taskId = params.get("task");

  const openTask = useCallback(
    (id: string) =>
      setParams((prev) => {
        const next = new URLSearchParams(prev);
        next.set("task", id);
        return next;
      }),
    [setParams],
  );
  const close = useCallback(
    () =>
      setParams((prev) => {
        const next = new URLSearchParams(prev);
        next.delete("task");
        return next;
      }),
    [setParams],
  );

  return (
    <TaskPanelContext.Provider value={openTask}>
      {children}
      {taskId && <TaskDrawer taskId={taskId} onClose={close} />}
    </TaskPanelContext.Provider>
  );
}

const isActive = (status: string) => status === "queued" || status === "running";
// Сколько строк ПК показывать сразу; остальные — по кнопке, чтобы панель не тормозила на 1000 ПК
const HOST_PAGE = 200;
// Подпись состояния одного ПК в строке списка
const ROW_LABEL: Record<HostState, string> = {
  waiting: "ждёт включения",
  ready: "в очереди",
  pending: "ждёт плейбук",
  queued: "в очереди",
  running: "выполняется",
  success: "успешно",
  failed: "ошибка",
  cancelled: "отменён",
};

function TaskDrawer({ taskId, onClose }: { taskId: string; onClose: () => void }) {
  const queryClient = useQueryClient();
  const openTask = useOpenTask();
  const { data: task, isLoading, error } = useTask(taskId);
  const canEdit = useCanEdit();
  const toast = useToast();
  const [busy, setBusy] = useState<"cancel" | "retry" | null>(null);

  const refresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: keys.task(taskId) });
    queryClient.invalidateQueries({ queryKey: ["task"] });
    queryClient.invalidateQueries({ queryKey: ["tasks"] });
    // Обновление и проверка агента меняют версии в реестре хостов
    if (task?.task_type.startsWith("agent_")) {
      queryClient.invalidateQueries({ queryKey: keys.hosts });
      queryClient.invalidateQueries({ queryKey: keys.agentVersions });
    }
    // Смена доступа применяется в конце задачи: учётки и группы хостов изменились
    if (task?.task_type === "access_change") {
      queryClient.invalidateQueries({ queryKey: keys.hosts });
      queryClient.invalidateQueries({ queryKey: keys.groups });
      queryClient.invalidateQueries({ queryKey: keys.credentials });
    }
  }, [queryClient, taskId, task?.task_type]);

  const counts = useMemo(() => (task ? countHostStates(task) : {}), [task]);
  const waitingCount = (counts.waiting ?? 0) + (counts.pending ?? 0);
  const failedHosts = useMemo(() => (task ? task.host_ids.filter((id) => hostStateOf(task, id) === "failed") : []), [task]);
  const canRetry = canEdit && task?.task_type === "playbook" && !!task.repo_id && !!task.playbook_name && failedHosts.length > 0 && !isActive(task.status);

  async function cancel() {
    if (!task) return;
    const question = task.grouped
      ? `Отменить ожидание на ${pcCount(waitingCount)}? Уже выполненное и выполняющееся не затрагивается.`
      : "Отменить задачу? Она не запустится.";
    if (!window.confirm(question)) return;
    setBusy("cancel");
    try {
      await apiClient.post(`/tasks/${taskId}/cancel`);
      refresh();
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось отменить") });
    } finally {
      setBusy(null);
    }
  }

  async function retryFailed() {
    if (!task) return;
    if (!window.confirm(`Запустить «${taskTitle(task)}» ещё раз на ${pcCount(failedHosts.length)} с ошибкой?`)) return;
    setBusy("retry");
    try {
      const { data } = await apiClient.post<{ task_run_id: string }>("/playbooks/run", {
        repo_id: task.repo_id,
        playbook_names: [task.playbook_name],
        host_ids: failedHosts,
        extra_vars: task.extra_vars ?? {},
        defer_offline: true,
      });
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      openTask(data.task_run_id);
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось запустить повтор") });
    } finally {
      setBusy(null);
    }
  }

  // У смены доступа в extra_vars лежит описание изменения, а не переменные плейбука
  const vars = task?.task_type === "access_change" ? [] : Object.entries(task?.extra_vars ?? {});
  const subtitle = task && (task.task_type === "playbook" ? task.playbook_name : TASK_TYPE_LABELS[task.task_type]);

  return (
    <Drawer
      open
      onClose={onClose}
      width="lg"
      title={task ? taskTitle(task) : "Задача"}
      subtitle={subtitle}
      actions={task && <Badge status={displayStatus(task)}>{STATUS_LABELS[displayStatus(task)] ?? task.status}</Badge>}
    >
      {isLoading && <Loading />}
      {error && <p className="text-sm text-rose-500">Задача не найдена или нет доступа</p>}
      {task && (
        <div className="space-y-5">
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
            <Meta label="Запустил">{task.created_by_name ?? (task.created_by ? "—" : "расписание")}</Meta>
            <Meta label="Создан">{formatDateTime(task.created_at)}</Meta>
            <Meta label="Длительность">{formatDuration(task.started_at, task.finished_at)}</Meta>
            <Meta label="ПК">{task.host_ids.length}</Meta>
          </dl>

          {task.playbook_description && <p className="text-sm text-muted-foreground">{task.playbook_description}</p>}

          {(task.chain?.length ?? 0) > 1 && <ChainSteps task={task} onOpen={openTask} />}

          {waitingCount > 0 && (
            <p className="flex items-start gap-2.5 rounded-lg border border-violet-500/25 bg-violet-500/5 px-3 py-2.5 text-sm text-foreground/90">
              <Clock className="mt-0.5 h-4 w-4 shrink-0 text-violet-600 dark:text-violet-300" />
              <span>
                {counts.waiting ? `${pcCount(counts.waiting)} не в сети — на каждом задача запустится сама, когда он появится (ждём до 7 дней). ` : ""}
                {counts.pending ? `${pcCount(counts.pending)} ждут, пока закончится предыдущий плейбук.` : ""}
              </span>
            </p>
          )}

          {(canRetry || (canEdit && waitingCount > 0)) && (
            <div className="flex flex-wrap gap-2">
              {canRetry && (
                <Button size="sm" variant="secondary" onClick={retryFailed} loading={busy === "retry"}>
                  <RotateCcw className="h-3.5 w-3.5" />
                  Повторить на ПК с ошибкой ({failedHosts.length})
                </Button>
              )}
              {canEdit && waitingCount > 0 && (
                <Button size="sm" variant="secondary" onClick={cancel} loading={busy === "cancel"}>
                  <XCircle className="h-3.5 w-3.5" />
                  Отменить ожидание ({waitingCount})
                </Button>
              )}
            </div>
          )}

          <TaskBody task={task} vars={vars} onRunDone={refresh} />
        </div>
      )}
    </Drawer>
  );
}

/** ПК запуска с их состоянием и журналы выполнения. */
function TaskBody({ task, vars, onRunDone }: { task: TaskRunDetail; vars: [string, unknown][]; onRunDone: () => void }) {
  const runs: TaskRun[] = useMemo(() => (task.grouped ? task.runs ?? [] : [task]), [task]);
  // Какая выполняющая задача у каждого ПК — последняя, где он был
  const runOfHost = useMemo(() => {
    const map = new Map<string, string>();
    for (const run of runs) for (const id of run.host_ids) map.set(id, run.id);
    return map;
  }, [runs]);
  const defaultRun = runs.find((r) => isActive(r.status))?.id ?? runs[runs.length - 1]?.id ?? null;
  const [selectedRun, setSelectedRun] = useState<string | null>(defaultRun);
  const logRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!selectedRun || !runs.some((r) => r.id === selectedRun)) setSelectedRun(defaultRun);
  }, [defaultRun, runs, selectedRun]);

  function showLog(runId: string) {
    setSelectedRun(runId);
    requestAnimationFrame(() => logRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }

  return (
    <>
      {task.host_ids.length > 1 && <HostList task={task} runOfHost={runOfHost} showLogLinks={runs.length > 1} onShowLog={showLog} />}
      {vars.length > 0 && (
        <div className="flex flex-wrap gap-1.5 text-xs">
          {vars.map(([k, v]) => (
            <span key={k} className="rounded-md bg-muted px-2 py-1 font-mono">
              {k}={String(v)}
            </span>
          ))}
        </div>
      )}
      <section ref={logRef} className="scroll-mt-4 space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-foreground">Журнал</h3>
          {runs.length > 1 && (
            <div className="flex flex-wrap gap-1" role="tablist" aria-label="Запуски">
              {runs.map((run, index) => (
                <button
                  key={run.id}
                  type="button"
                  role="tab"
                  aria-selected={run.id === selectedRun}
                  onClick={() => setSelectedRun(run.id)}
                  title={`${formatDateTime(run.created_at)} · ${pcCount(run.host_ids.length)} · ${STATUS_LABELS[run.status] ?? run.status}`}
                  className={`inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs transition-colors ${
                    run.id === selectedRun ? "bg-surface text-foreground shadow-panel ring-1 ring-border" : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  }`}
                >
                  <span className={`h-1.5 w-1.5 rounded-full ${HOST_STATE_INFO[hostStateOf({ status: run.status }, "")].dot}`} />
                  {formatDateTime(run.created_at)} · {run.host_ids.length} ПК
                  <span className="sr-only">{index + 1}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        {selectedRun ? (
          <RunLog runId={selectedRun} own={selectedRun === task.id ? task : undefined} onDone={onRunDone} />
        ) : (
          <p className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-sm text-muted-foreground">
            Пока ничего не выполнялось: ПК ждут включения.
          </p>
        )}
        {task.grouped && task.log_output && (
          <details className="rounded-lg border border-border px-3 py-2 text-sm">
            <summary className="cursor-pointer text-muted-foreground">События запуска: ожидание, появление ПК, переназначения</summary>
            <pre className="mt-2 whitespace-pre-wrap font-mono text-xs leading-relaxed text-foreground/80">{task.log_output}</pre>
          </details>
        )}
      </section>
    </>
  );
}

function RunLog({ runId, own, onDone }: { runId: string; own?: TaskRunDetail; onDone: () => void }) {
  const { data } = useTask(own ? null : runId);
  const run = own ?? data;
  if (!run) return <Loading />;
  return (
    <div className="space-y-2">
      {run.run_as && <RunAsSummary runAs={run.run_as} />}
      {isActive(run.status) ? (
        <TaskLog taskId={run.id} onDone={onDone} />
      ) : (
        <pre className="console-block max-h-[65vh] whitespace-pre-wrap">{run.log_output || "Лог пуст"}</pre>
      )}
    </div>
  );
}

function HostList({
  task,
  runOfHost,
  showLogLinks,
  onShowLog,
}: {
  task: TaskRunDetail;
  runOfHost: Map<string, string>;
  showLogLinks: boolean;
  onShowLog: (runId: string) => void;
}) {
  const { hostById } = useFleet();
  const counts = useMemo(() => countHostStates(task), [task]);
  const [filter, setFilter] = useState<HostState | "all">("all");
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(HOST_PAGE);

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    const order = new Map(HOST_STATES.map((s, i) => [s.key, i]));
    return task.host_ids
      .map((id) => {
        const host = hostById.get(id);
        return { id, label: host ? hostLabel(host) : "удалённый хост", state: hostStateOf(task, id) };
      })
      .filter((r) => (filter === "all" || r.state === filter) && (!q || r.label.toLowerCase().includes(q)))
      .sort((a, b) => (order.get(a.state) ?? 9) - (order.get(b.state) ?? 9) || a.label.localeCompare(b.label, "ru", { numeric: true }));
  }, [task, hostById, filter, search]);

  const chips = HOST_STATES.filter((s) => counts[s.key]);
  return (
    <section className="space-y-3">
      <div className="space-y-2">
        <div className="flex items-baseline justify-between gap-2">
          <h3 className="text-sm font-semibold text-foreground">ПК</h3>
          <span className="text-xs tabular-nums text-muted-foreground">
            завершено {finishedCount(counts)} из {task.host_ids.length}
          </span>
        </div>
        <HostStateBar counts={counts} />
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Фильтр по состоянию">
          <FilterChip active={filter === "all"} onClick={() => setFilter("all")} label="Все" count={task.host_ids.length} />
          {chips.map((s) => (
            <FilterChip key={s.key} active={filter === s.key} onClick={() => setFilter(s.key)} label={s.label} count={counts[s.key] ?? 0} dot={s.dot} />
          ))}
        </div>
        {task.host_ids.length > 12 && <SearchInput value={search} onChange={setSearch} placeholder="Имя ПК" className="w-full sm:ml-auto sm:w-48" />}
      </div>
      <div className="max-h-80 overflow-y-auto rounded-lg border border-border">
        <ul className="divide-y divide-border text-sm">
          {rows.slice(0, limit).map((r) => {
            const info = HOST_STATE_INFO[r.state];
            const runId = runOfHost.get(r.id);
            return (
              <li key={r.id} className="flex items-center gap-3 px-3 py-1.5">
                <span className="min-w-0 flex-1 truncate font-mono text-xs text-foreground">{r.label}</span>
                <span className={`inline-flex shrink-0 items-center gap-1.5 text-xs ${info.text}`}>
                  <span className={`h-1.5 w-1.5 rounded-full ${info.dot}`} />
                  {ROW_LABEL[r.state]}
                </span>
                {showLogLinks &&
                  (runId ? (
                    <button
                      type="button"
                      className="inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-xs text-blue-600 hover:bg-muted dark:text-blue-400"
                      onClick={() => onShowLog(runId)}
                      aria-label={`Журнал ${r.label}`}
                    >
                      <ScrollText className="h-3.5 w-3.5" />
                      журнал
                    </button>
                  ) : (
                    <span className="w-[66px] shrink-0" aria-hidden />
                  ))}
              </li>
            );
          })}
        </ul>
        {rows.length === 0 && <p className="px-3 py-4 text-center text-sm text-muted-foreground">Нет ПК</p>}
        {rows.length > limit && (
          <button type="button" className="w-full border-t border-border py-2 text-xs text-blue-600 hover:bg-muted dark:text-blue-400" onClick={() => setLimit((l) => l + HOST_PAGE)}>
            Показать ещё {Math.min(HOST_PAGE, rows.length - limit)} из {rows.length - limit}
          </button>
        )}
      </div>
    </section>
  );
}

function FilterChip({ active, onClick, label, count, dot }: { active: boolean; onClick: () => void; label: string; count: number; dot?: string }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={active}
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset transition-colors ${
        active ? "bg-foreground text-background ring-foreground" : "text-muted-foreground ring-border hover:text-foreground"
      }`}
    >
      {dot && <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />}
      {label}
      <span className="tabular-nums opacity-70">{count}</span>
    </button>
  );
}

/** Плейбуки одного запуска по порядку: где мы и что дальше. */
function ChainSteps({ task, onOpen }: { task: TaskRunDetail; onOpen: (id: string) => void }) {
  return (
    <nav aria-label="Цепочка плейбуков" className="space-y-1.5">
      <p className="text-xs text-muted-foreground">Цепочка плейбуков — выполняются по очереди</p>
      <ol className="flex flex-wrap items-center gap-1.5 text-xs">
        {task.chain.map((step, index) => {
          const current = step.id === task.id;
          return (
            <li key={step.id} className="flex items-center gap-1.5">
              {index > 0 && <span className="text-subtle" aria-hidden>→</span>}
              <button
                type="button"
                onClick={() => !current && onOpen(step.id)}
                aria-current={current ? "step" : undefined}
                className={`inline-flex items-center gap-1.5 rounded-md px-2 py-1 ring-1 ring-inset ${
                  current ? "bg-muted font-medium text-foreground ring-border" : "text-muted-foreground ring-transparent hover:bg-muted hover:text-foreground"
                }`}
              >
                <span className="tabular-nums text-subtle">{index + 1}.</span>
                {step.playbook_title || playbookShortName(step.playbook_name ?? "")}
                <Badge status={step.status} className="px-1.5 py-0">{STATUS_LABELS[step.status] ?? step.status}</Badge>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** От чьего имени шёл плейбук: инициатор там, где он администратор ПК, иначе учётка установки */
function RunAsSummary({ runAs }: { runAs: RunAs }) {
  const { hostById } = useFleet();
  const fallback = Object.entries(runAs.fallback ?? {});
  if (!runAs.login) {
    return <p className="text-sm text-muted-foreground">От учётки установки агента: {runAs.reason}</p>;
  }
  return (
    <div className="space-y-1 text-sm">
      <p className="text-muted-foreground">
        {runAs.as_user.length > 0 && (
          <>
            От имени <span className="font-mono text-foreground">{runAs.login}</span> на {pcCount(runAs.as_user.length)}
          </>
        )}
        {runAs.as_user.length > 0 && fallback.length > 0 && "; "}
        {fallback.length > 0 && <>от учётки установки агента на {pcCount(fallback.length)}</>}
      </p>
      {fallback.length > 0 && (
        <details className="rounded-lg border border-border px-3 py-2">
          <summary className="cursor-pointer text-muted-foreground">Где вход под {runAs.login} не прошёл</summary>
          <ul className="mt-2 space-y-0.5 text-xs">
            {fallback.map(([id, why]) => (
              <li key={id}>
                <span className="font-mono text-foreground">{hostById.get(id)?.hostname ?? id}</span> — {why}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function Meta({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 font-medium text-foreground">{children}</dd>
    </div>
  );
}
