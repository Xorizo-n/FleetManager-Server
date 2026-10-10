import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useFleet, useTasks } from "../api/queries";
import type { TaskRun } from "../api/types";
import PageHeader from "../components/ui/PageHeader";
import Badge from "../components/ui/Badge";
import Button from "../components/ui/Button";
import SearchInput from "../components/ui/SearchInput";
import { Empty, Loading } from "../components/ui/States";
import { useOpenTask } from "../components/TaskPanel";
import { formatDateTime, formatDuration, hostLabel, STATUS_LABELS, TASK_TYPE_LABELS, taskTitle } from "../lib/format";

const PAGE = 100;

export default function Tasks() {
  const [params] = useSearchParams();
  const [type, setType] = useState(params.get("type") ?? "");
  const [status, setStatus] = useState(params.get("status") ?? "");
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const { hostById } = useFleet();
  const openTask = useOpenTask();
  const { data, isLoading, isFetching } = useTasks({ task_type: type || undefined, status_filter: status || undefined, limit });

  const targetsOf = (t: TaskRun) => t.host_ids.map((id) => { const h = hostById.get(id); return h ? hostLabel(h) : "удалённый хост"; });

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return data ?? [];
    return (data ?? []).filter((t) =>
      [taskTitle(t), t.playbook_name, t.created_by_name, ...targetsOf(t)].filter(Boolean).join(" ").toLowerCase().includes(q),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, search, hostById]);

  const running = (data ?? []).filter((t) => t.status === "running" || t.status === "queued").length;

  return (
    <div className="animate-fade-in space-y-4">
      <PageHeader
        title="Задачи"
        description={running > 0 ? `Выполняется сейчас: ${running}` : "Журнал запусков плейбуков, сканирований, диагностик и обновлений агента"}
      />
      <div className="flex flex-wrap items-center gap-2">
        <SearchInput value={search} onChange={setSearch} placeholder="Плейбук, хост или автор" className="min-w-[220px] flex-1" />
        <select value={type} onChange={(e) => { setType(e.target.value); setLimit(PAGE); }} className="input-base w-auto py-2" aria-label="Тип задачи">
          <option value="">Все типы</option>
          {Object.entries(TASK_TYPE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <select value={status} onChange={(e) => { setStatus(e.target.value); setLimit(PAGE); }} className="input-base w-auto py-2" aria-label="Статус">
          <option value="">Любой статус</option>
          {["queued", "running", "success", "failed"].map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
        </select>
      </div>

      <div className="table-shell">
        <table className="table-base">
          <thead>
            <tr>
              <th>Задача</th>
              <th>Цели</th>
              <th>Запустил</th>
              <th>Создана</th>
              <th>Длительность</th>
              <th>Статус</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => {
              const targets = targetsOf(t);
              return (
                <tr
                  key={t.id}
                  tabIndex={0}
                  className="is-interactive"
                  onClick={() => openTask(t.id)}
                  onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), openTask(t.id))}
                >
                  <td className="max-w-[320px]">
                    <div className="truncate font-medium text-foreground">{taskTitle(t)}</div>
                    {t.task_type === "playbook" && <div className="truncate text-xs text-subtle">{t.playbook_name}</div>}
                  </td>
                  <td className="max-w-[260px] text-muted-foreground">
                    <div className="truncate" title={targets.join(", ")}>
                      {targets.length === 0 ? "—" : targets.slice(0, 2).join(", ")}
                      {targets.length > 2 && <span className="text-subtle"> +{targets.length - 2}</span>}
                    </div>
                  </td>
                  <td className="text-muted-foreground">{t.created_by_name ?? (t.created_by ? "—" : "расписание")}</td>
                  <td className="whitespace-nowrap text-muted-foreground">{formatDateTime(t.created_at)}</td>
                  <td className="whitespace-nowrap text-muted-foreground">{formatDuration(t.started_at, t.finished_at)}</td>
                  <td><Badge status={t.status}>{STATUS_LABELS[t.status] ?? t.status}</Badge></td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {isLoading && <Loading />}
        {!isLoading && rows.length === 0 && <Empty>{search ? "Ничего не найдено" : "Задач нет"}</Empty>}
      </div>
      {(data?.length ?? 0) >= limit && (
        <div className="flex justify-center">
          <Button variant="secondary" onClick={() => setLimit((l) => l + PAGE)} loading={isFetching}>
            Показать ещё
          </Button>
        </div>
      )}
    </div>
  );
}
