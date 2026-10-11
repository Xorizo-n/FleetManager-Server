import { createContext, ReactNode, useCallback, useContext, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import Drawer from "./ui/Drawer";
import Badge from "./ui/Badge";
import Button from "./ui/Button";
import { useToast } from "./ui/Toast";
import { Clock } from "lucide-react";
import { apiClient } from "../api/client";
import TaskLog from "./TaskLog";
import { Loading } from "./ui/States";
import { keys, useCanEdit, useFleet, useTask } from "../api/queries";
import { apiError, formatDateTime, formatDuration, hostLabel, STATUS_LABELS, TASK_TYPE_LABELS, taskTitle } from "../lib/format";

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

function TaskDrawer({ taskId, onClose }: { taskId: string; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { data: task, isLoading, error } = useTask(taskId);
  const { hostById } = useFleet();
  const running = task && ["queued", "running"].includes(task.status);
  const canEdit = useCanEdit();
  const toast = useToast();
  const [cancelling, setCancelling] = useState(false);

  async function cancel() {
    if (!window.confirm("Отменить задачу? Она не запустится, даже когда ПК появится в сети.")) return;
    setCancelling(true);
    try {
      await apiClient.post(`/tasks/${taskId}/cancel`);
      queryClient.invalidateQueries({ queryKey: keys.task(taskId) });
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось отменить задачу") });
    } finally {
      setCancelling(false);
    }
  }

  const hostNames = useMemo(
    () => (task?.host_ids ?? []).map((id) => { const h = hostById.get(id); return h ? hostLabel(h) : id.slice(0, 8); }),
    [task?.host_ids, hostById],
  );

  function handleDone() {
    queryClient.invalidateQueries({ queryKey: keys.task(taskId) });
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
  }

  // У смены доступа в extra_vars лежит описание изменения, а не переменные плейбука
  const vars = task?.task_type === "access_change" ? [] : Object.entries(task?.extra_vars ?? {});

  return (
    <Drawer
      open
      onClose={onClose}
      width="lg"
      title={task ? taskTitle(task) : "Задача"}
      subtitle={task && (task.task_type === "playbook" ? task.playbook_name : TASK_TYPE_LABELS[task.task_type])}
      actions={task && <Badge status={task.status}>{STATUS_LABELS[task.status] ?? task.status}</Badge>}
    >
      {isLoading && <Loading />}
      {error && <p className="text-sm text-rose-500">Задача не найдена или нет доступа</p>}
      {task && (
        <div className="space-y-4">
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
            <Meta label="Запустил">{task.created_by_name ?? (task.created_by ? "—" : "расписание")}</Meta>
            <Meta label="Создана">{formatDateTime(task.created_at)}</Meta>
            <Meta label="Длительность">{formatDuration(task.started_at, task.finished_at)}</Meta>
            <Meta label="Хостов">{task.host_ids.length}</Meta>
          </dl>
          {hostNames.length > 0 && (
            <details className="rounded-lg border border-border px-3 py-2 text-sm" open={hostNames.length <= 12}>
              <summary className="cursor-pointer text-muted-foreground">Цели ({hostNames.length})</summary>
              <p className="mt-2 font-mono text-xs leading-relaxed text-foreground/80">{hostNames.join(", ")}</p>
            </details>
          )}
          {vars.length > 0 && (
            <div className="flex flex-wrap gap-1.5 text-xs">
              {vars.map(([k, v]) => (
                <span key={k} className="rounded-md bg-muted px-2 py-1 font-mono">
                  {k}={String(v)}
                </span>
              ))}
            </div>
          )}
          {task.status === "waiting" && (
            <div className="flex flex-wrap items-center gap-3 rounded-lg border border-violet-500/30 bg-violet-500/5 px-3 py-2.5 text-sm">
              <Clock className="h-4 w-4 shrink-0 text-violet-600 dark:text-violet-300" />
              <span className="min-w-0 flex-1 text-foreground/90">
                ПК не в сети. Задача запустится сама, как только он пришлёт heartbeat или ответит по SSH.
              </span>
              {canEdit && (
                <Button size="sm" variant="secondary" onClick={cancel} loading={cancelling}>
                  Отменить
                </Button>
              )}
            </div>
          )}
          {running ? (
            <TaskLog taskId={task.id} onDone={handleDone} />
          ) : (
            <pre className="console-block max-h-[65vh] whitespace-pre-wrap">{task.log_output || "Лог пуст"}</pre>
          )}
        </div>
      )}
    </Drawer>
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
