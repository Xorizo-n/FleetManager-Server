import { useEffect, useRef, useState } from "react";
import { apiClient } from "../api/client";
import TaskLog from "../components/TaskLog";
import Badge from "../components/ui/Badge";

interface TaskRunOut {
  id: string;
  task_type: string;
  playbook_name: string | null;
  host_ids: string[];
  status: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

interface TaskRunDetail extends TaskRunOut {
  log_output: string | null;
  extra_vars: Record<string, unknown> | null;
}

const RUNNING_STATUSES = new Set(["queued", "running"]);

const TASK_TYPE_LABELS: Record<string, string> = {
  host_diagnostic:   "Диагностика",
  playbook:          "Плейбук",
  agent_update:      "Обновление агента",
  software_scan:     "Сканирование ПО",
};

const STATUS_LABELS: Record<string, string> = {
  queued:  "В очереди",
  running: "Выполняется",
  success: "Выполнена",
  failed:  "Ошибка",
};

function taskLabel(t: TaskRunOut) {
  return t.playbook_name || TASK_TYPE_LABELS[t.task_type] || t.task_type;
}

export default function Tasks() {
  const [tasks, setTasks] = useState<TaskRunOut[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<TaskRunDetail | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const detailRef = useRef<TaskRunDetail | null>(null);
  detailRef.current = detail;

  async function loadTasks() {
    const { data } = await apiClient.get<TaskRunOut[]>("/tasks", {
      params: { status_filter: statusFilter || undefined },
    });
    setTasks(data);
    return data;
  }

  async function loadDetail(id: string) {
    const { data } = await apiClient.get<TaskRunDetail>(`/tasks/${id}`);
    setDetail(data);
  }

  useEffect(() => {
    loadTasks();
    const interval = setInterval(async () => {
      const data = await loadTasks();
      // If the selected task status changed to terminal → re-fetch detail
      if (detailRef.current && RUNNING_STATUSES.has(detailRef.current.status)) {
        const updated = data.find((t) => t.id === detailRef.current!.id);
        if (updated && !RUNNING_STATUSES.has(updated.status)) {
          loadDetail(updated.id);
        }
      }
    }, 5000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    loadDetail(selectedId);
  }, [selectedId]);

  function handleDone(id: string) {
    // SSE finished — reload detail to get final log_output from DB
    loadDetail(id);
  }

  return (
    <div className="animate-fade-in space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Задачи</h1>
        <select
          aria-label="Фильтр по статусу"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="input-base w-auto py-2 text-sm"
        >
          <option value="">Любой статус</option>
          <option value="queued">В очереди</option>
          <option value="running">Выполняется</option>
          <option value="success">Выполнена</option>
          <option value="failed">Ошибка</option>
        </select>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="table-shell">
          <table className="table-base">
            <thead>
              <tr>
                <th>Тип / Плейбук</th>
                <th>Статус</th>
                <th>Создана</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((t) => (
                <tr
                  key={t.id}
                  role="row"
                  tabIndex={0}
                  aria-selected={selectedId === t.id}
                  onClick={() => setSelectedId(t.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      setSelectedId(t.id);
                    }
                  }}
                  className={`is-interactive ${selectedId === t.id ? "bg-muted/60" : ""}`}
                >
                  <td>{taskLabel(t)}</td>
                  <td>
                    <Badge status={t.status}>{STATUS_LABELS[t.status] ?? t.status}</Badge>
                  </td>
                  <td className="text-muted-foreground">
                    {new Date(t.created_at).toLocaleString("ru-RU")}
                  </td>
                </tr>
              ))}
              {tasks.length === 0 && (
                <tr>
                  <td colSpan={3} className="px-3 py-8 text-center text-subtle">
                    Задач нет
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="surface-panel">
          {!detail && (
            <p className="text-subtle">Выберите задачу для просмотра лога</p>
          )}
          {detail && (
            <div className="animate-fade-in space-y-3">
              <div className="flex items-center justify-between text-sm">
                <span className="font-medium text-foreground">{taskLabel(detail)}</span>
                <Badge status={detail.status}>
                  {STATUS_LABELS[detail.status] ?? detail.status}
                </Badge>
              </div>
              <p className="text-xs text-subtle">
                Хостов: {detail.host_ids.length}
                {detail.started_at && (
                  <> · Старт: {new Date(detail.started_at).toLocaleTimeString("ru-RU")}</>
                )}
                {detail.finished_at && (
                  <> · Завершена: {new Date(detail.finished_at).toLocaleTimeString("ru-RU")}</>
                )}
              </p>
              {RUNNING_STATUSES.has(detail.status) ? (
                <TaskLog taskId={detail.id} onDone={() => handleDone(detail.id)} />
              ) : (
                <pre className="console-block">
                  {detail.log_output || "Лог пуст"}
                </pre>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
