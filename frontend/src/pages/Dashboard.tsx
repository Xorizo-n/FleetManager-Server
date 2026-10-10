import { ReactNode, useMemo } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ArrowUpCircle, BellRing, ChevronRight, Clock, PlugZap, XCircle } from "lucide-react";
import { apiClient } from "../api/client";
import { useAlertSummary, useFleet, useTasks } from "../api/queries";
import { useTheme } from "../context/ThemeContext";
import Card from "../components/ui/Card";
import Badge from "../components/ui/Badge";
import PageHeader from "../components/ui/PageHeader";
import { useOpenTask } from "../components/TaskPanel";
import { formatDateTime, pcCount, plural, STATUS_LABELS, taskTitle } from "../lib/format";

const DAY = 86_400_000;

export default function Dashboard() {
  const { theme } = useTheme();
  const openTask = useOpenTask();
  const { hosts, agentVersions, isLoading } = useFleet();
  const timeline = useQuery({ queryKey: ["dashboard", "timeline"], queryFn: () => apiClient.get<{ hour: string; online: number }[]>("/dashboard/online-timeline").then((r) => r.data) });
  const weekly = useQuery({ queryKey: ["dashboard", "weekly"], queryFn: () => apiClient.get<{ day: string; success: number; failed: number }[]>("/dashboard/weekly-run-stats").then((r) => r.data) });
  const recent = useTasks({ limit: 50 }, 10_000);
  // Счётчик считает сервер: раньше бралось 50 последних алертов, и цифра упиралась в 50
  const alerts = useAlertSummary(7);

  const stats = useMemo(() => {
    const now = Date.now();
    return {
      total: hosts.length,
      online: hosts.filter((h) => h.status === "online").length,
      offline: hosts.filter((h) => h.status === "offline").length,
      withoutAgent: hosts.filter((h) => !h.has_agent).length,
      stale: hosts.filter((h) => !h.last_checked_at || now - new Date(h.last_checked_at).getTime() > 7 * DAY).length,
    };
  }, [hosts]);

  const failed24h = (recent.data ?? []).filter((t) => t.status === "failed" && Date.now() - new Date(t.created_at).getTime() < DAY).length;
  const running = (recent.data ?? []).filter((t) => t.status === "running" || t.status === "queued").length;
  const alerts7d = alerts.data?.total ?? 0;
  const alertHosts = alerts.data?.hosts ?? 0;
  const outdated = agentVersions?.outdated ?? 0;

  const isDark = theme === "dark";
  const chart = {
    grid: isDark ? "#1e293b" : "#e2e8f0",
    tick: isDark ? "#94a3b8" : "#64748b",
    tooltip: { background: isDark ? "#0f172a" : "#ffffff", border: `1px solid ${isDark ? "#1e293b" : "#e2e8f0"}`, borderRadius: 8, fontSize: 12, color: isDark ? "#f1f5f9" : "#0f172a" },
  };

  const attention: { show: boolean; icon: ReactNode; text: string; to: string; tone: string }[] = [
    { show: failed24h > 0, icon: <XCircle className="h-4 w-4" />, text: `${plural(failed24h, "задача завершилась", "задачи завершились", "задач завершились")} ошибкой за сутки`, to: "/tasks?status=failed", tone: "text-rose-600 dark:text-rose-400" },
    { show: outdated > 0, icon: <ArrowUpCircle className="h-4 w-4" />, text: `Устаревший агент на ${pcCount(outdated)} (актуальная ${agentVersions?.available_version ?? "—"})`, to: "/hosts?agent=outdated", tone: "text-amber-600 dark:text-amber-400" },
    { show: stats.stale > 0, icon: <Clock className="h-4 w-4" />, text: `${pcCount(stats.stale)} не проверялись больше 7 дней`, to: "/hosts?checked=older", tone: "text-amber-600 dark:text-amber-400" },
    { show: alerts7d > 0, icon: <BellRing className="h-4 w-4" />, text: `${plural(alerts7d, "алерт", "алерта", "алертов")} от агентов за неделю на ${pcCount(alertHosts)} (смена оборудования)`, to: "/hosts", tone: "text-amber-600 dark:text-amber-400" },
    { show: stats.withoutAgent > 0, icon: <PlugZap className="h-4 w-4" />, text: `${pcCount(stats.withoutAgent)} без агента`, to: "/hosts?agent=without", tone: "text-muted-foreground" },
  ];
  const attentionItems = attention.filter((a) => a.show);

  const tiles = [
    { label: "Всего хостов", value: stats.total, to: "/hosts", accent: "text-foreground" },
    { label: "Online", value: stats.online, to: "/hosts?status=online", accent: "text-emerald-600 dark:text-emerald-400" },
    { label: "Offline", value: stats.offline, to: "/hosts?status=offline", accent: "text-rose-600 dark:text-rose-400" },
    { label: "Выполняется задач", value: running, to: "/tasks?status=running", accent: running ? "text-sky-600 dark:text-sky-400" : "text-foreground" },
  ];

  return (
    <div className="animate-fade-in space-y-6">
      <PageHeader title="Обзор" />

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {tiles.map((t) => (
          <Link key={t.label} to={t.to} className="surface-panel group transition-colors hover:border-blue-500/40">
            <div className="flex items-center justify-between text-sm font-medium text-muted-foreground">
              {t.label}
              <ChevronRight className="h-4 w-4 opacity-0 transition-opacity group-hover:opacity-100" />
            </div>
            <p className={`mt-2 text-3xl font-bold tabular-nums ${t.accent}`}>
              {isLoading ? <span className="inline-block h-8 w-12 animate-pulse rounded-md bg-muted" /> : t.value}
            </p>
          </Link>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <Card title="Требует внимания">
          {attentionItems.length === 0 ? (
            <p className="py-6 text-center text-sm text-subtle">Всё в порядке</p>
          ) : (
            <ul className="-mx-2">
              {attentionItems.map((a) => (
                <li key={a.to + a.text}>
                  <Link to={a.to} className="flex items-center gap-3 rounded-lg px-2 py-2.5 text-sm hover:bg-muted">
                    <span className={a.tone}>{a.icon}</span>
                    <span className="flex-1 text-foreground">{a.text}</span>
                    <ChevronRight className="h-4 w-4 text-subtle" />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Последние задачи" action={<Link to="/tasks" className="text-xs text-blue-600 hover:underline dark:text-blue-400">Все задачи</Link>}>
          <ul className="-mx-2">
            {(recent.data ?? []).slice(0, 7).map((t) => (
              <li key={t.id}>
                <button onClick={() => openTask(t.id)} className="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left text-sm hover:bg-muted">
                  <span className="min-w-0 flex-1 truncate text-foreground">{taskTitle(t)}</span>
                  <span className="hidden shrink-0 text-xs text-muted-foreground sm:inline">{pcCount(t.host_ids.length)}</span>
                  <span className="hidden shrink-0 text-xs text-muted-foreground md:inline">{t.created_by_name ?? "расписание"}</span>
                  <span className="shrink-0 text-xs text-muted-foreground">{formatDateTime(t.created_at)}</span>
                  <Badge status={t.status}>{STATUS_LABELS[t.status]}</Badge>
                </button>
              </li>
            ))}
            {recent.data?.length === 0 && <p className="py-6 text-center text-sm text-subtle">Задач ещё не было</p>}
          </ul>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Online за последние 24 часа">
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={timeline.data ?? []}>
              <CartesianGrid strokeDasharray="3 3" stroke={chart.grid} />
              <XAxis dataKey="hour" tick={{ fontSize: 10, fill: chart.tick }} interval={3} tickFormatter={(v: string) => v.slice(-5)} />
              <YAxis tick={{ fontSize: 10, fill: chart.tick }} allowDecimals={false} />
              <Tooltip contentStyle={chart.tooltip} formatter={(v) => [v, "online"]} />
              <Line type="monotone" dataKey="online" stroke="#3b82f6" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </Card>
        <Card title="Задачи за 7 дней">
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={weekly.data ?? []}>
              <CartesianGrid strokeDasharray="3 3" stroke={chart.grid} />
              <XAxis dataKey="day" tick={{ fontSize: 10, fill: chart.tick }} />
              <YAxis tick={{ fontSize: 10, fill: chart.tick }} allowDecimals={false} />
              <Tooltip contentStyle={chart.tooltip} cursor={{ fill: isDark ? "rgba(148,163,184,0.08)" : "rgba(100,116,139,0.08)" }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="success" name="успешно" stackId="runs" fill="#10b981" />
              <Bar dataKey="failed" name="с ошибкой" stackId="runs" fill="#f43f5e" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>

    </div>
  );
}
