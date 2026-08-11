import { useEffect, useState } from "react";
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

export default function Tasks() {
  const [tasks, setTasks] = useState<TaskRunOut[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<TaskRunDetail | null>(null);
  const [statusFilter, setStatusFilter] = useState("");

  async function loadTasks() {
    const { data } = await apiClient.get<TaskRunOut[]>("/tasks", {
      params: { status_filter: statusFilter || undefined },
    });
    setTasks(data);
  }

  useEffect(() => {
    loadTasks();
    const interval = setInterval(loadTasks, 5000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    apiClient.get<TaskRunDetail>(`/tasks/${selectedId}`).then((r) => setDetail(r.data));
  }, [selectedId]);

  return (
    <div className="animate-fade-in space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Задачи</h1>
        <select aria-label="Фильтр по статусу" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="input-base w-auto py-2 text-sm">
          <option value="">Любой статус</option>
          <option value="queued">queued</option>
          <option value="running">running</option>
          <option value="success">success</option>
          <option value="failed">failed</option>
        </select>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="table-shell">
          <table className="table-base">
            <thead>
              <tr>
                <th>Тип</th>
                <th>Плейбук</th>
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
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSelectedId(t.id); } }}
                  className={`is-interactive ${selectedId === t.id ? "bg-muted/60" : ""}`}
                >
                  <td>{t.task_type}</td>
                  <td>{t.playbook_name || "—"}</td>
                  <td><Badge status={t.status} /></td>
                  <td className="text-muted-foreground">{new Date(t.created_at).toLocaleString()}</td>
                </tr>
              ))}
              {tasks.length === 0 && (
                <tr><td colSpan={4} className="px-3 py-8 text-center text-subtle">Задач нет</td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="surface-panel">
          {!detail && <p className="text-subtle">Выберите задачу для просмотра лога</p>}
          {detail && (
            <div className="animate-fade-in space-y-3">
              <div className="flex items-center justify-between text-sm">
                <span className="font-medium text-foreground">{detail.playbook_name || detail.task_type}</span>
                <Badge status={detail.status} />
              </div>
              <p className="text-xs text-subtle">Хостов: {detail.host_ids.length}</p>
              {RUNNING_STATUSES.has(detail.status) ? (
                <TaskLog taskId={detail.id} />
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
