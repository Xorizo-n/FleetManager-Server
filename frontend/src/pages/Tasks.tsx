import { ReactNode, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useFleet, useTasks } from "../api/queries";
import type { TaskRun } from "../api/types";
import PageHeader from "../components/ui/PageHeader";
import Tabs from "../components/ui/Tabs";
import Badge from "../components/ui/Badge";
import Button from "../components/ui/Button";
import SearchInput from "../components/ui/SearchInput";
import { Empty, Loading } from "../components/ui/States";
import { useOpenTask } from "../components/TaskPanel";
import HostStateBar from "../components/HostStateBar";
import { countHostStates, displayStatus } from "../lib/hostStates";
import { formatDateTime, formatDuration, hostLabel, pcCount, STATUS_LABELS, TASK_TYPE_LABELS, taskTitle } from "../lib/format";
import Rollouts from "./tasks/Rollouts";

const PAGE = 100;

type Tab = "runs" | "rollouts";

export default function Tasks() {
  const [params, setParams] = useSearchParams();
  const tab: Tab = params.get("tab") === "rollouts" ? "rollouts" : "runs";
  const tabs = (
    <Tabs<Tab>
      value={tab}
      onChange={(id) => setParams(id === "runs" ? {} : { tab: id })}
      tabs={[
        { id: "runs", label: "Запуски" },
        { id: "rollouts", label: "Раскатка ПО" },
      ]}
    />
  );
  return tab === "rollouts" ? <Rollouts tabs={tabs} /> : <TaskJournal tabs={tabs} />;
}

/** Журнал запусков плейбуков, сканирований, диагностик и обновлений агента. */
function TaskJournal({ tabs }: { tabs: ReactNode }) {
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
  const pending = (data ?? []).filter((t) => t.status === "pending").length;
  const waitingHosts = (data ?? []).reduce((n, t) => n + (t.finished_at ? 0 : countHostStates(t).waiting ?? 0), 0);
  const summary = [
    running > 0 && `Выполняется сейчас: ${running}`,
    pending > 0 && `ждут предыдущий плейбук: ${pending}`,
    waitingHosts > 0 && `ждут включения: ${pcCount(waitingHosts)}`,
  ].filter(Boolean).join(" · ");

  return (
    <div className="animate-fade-in space-y-4">
      <PageHeader
        title="Задачи"
        description={summary || "Журнал запусков плейбуков, сканирований, диагностик и обновлений агента"}
      />
      {tabs}
      <div className="flex flex-wrap items-center gap-2">
        <SearchInput value={search} onChange={setSearch} placeholder="Плейбук, хост или автор" className="min-w-[220px] flex-1" />
        <select value={type} onChange={(e) => { setType(e.target.value); setLimit(PAGE); }} className="input-base w-auto py-2" aria-label="Тип задачи">
          <option value="">Все типы</option>
          {Object.entries(TASK_TYPE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <select value={status} onChange={(e) => { setStatus(e.target.value); setLimit(PAGE); }} className="input-base w-auto py-2" aria-label="Статус">
          <option value="">Любой статус</option>
          {["waiting", "pending", "queued", "running", "success", "failed", "cancelled"].map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
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
                  <td>
                    <div className="flex flex-col items-start gap-1.5">
                      <Badge status={displayStatus(t)}>{STATUS_LABELS[displayStatus(t)] ?? t.status}</Badge>
                      {t.host_ids.length > 1 && t.host_states && <HostStateBar counts={countHostStates(t)} compact />}
                    </div>
                  </td>
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
