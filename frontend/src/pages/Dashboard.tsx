import { useEffect, useState } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from "recharts";
import { Download, RefreshCw, Server, CheckCircle2, XCircle, HelpCircle } from "lucide-react";
import { apiClient, getAccessToken } from "../api/client";
import { useTheme } from "../context/ThemeContext";
import { useAuth } from "../context/AuthContext";
import Card from "../components/ui/Card";
import Badge from "../components/ui/Badge";
import Button from "../components/ui/Button";

interface HostsSummary {
  total: number;
  online: number;
  offline: number;
  unknown: number;
}

interface TaskRunOut {
  id: string;
  task_type: string;
  playbook_name: string | null;
  status: string;
  created_at: string;
}

interface SoftwareSummaryItem {
  name: string;
  version: string | null;
  host_count: number;
}

interface SoftwareHistoryOut {
  id: string;
  name: string;
  old_version: string | null;
  new_version: string | null;
  change_type: string;
  changed_at: string;
}

interface InstallerFile {
  name: string;
  size: number;
  mtime: string;
}

interface AgentVersionOverview {
  available_version: string | null;
  installer_present: boolean;
  total_agents: number;
  up_to_date: number;
  outdated: number;
  unknown: number;
  hosts: { host_id: string; hostname: string | null; agent_version: string | null; version_status: string }[];
}

const AGENT_INSTALLER_NAME = "FleetManagerAgent-Setup.exe";

const STAT_CARDS: {
  key: keyof HostsSummary;
  label: string;
  icon: typeof Server;
  accent: string;
}[] = [
  { key: "total", label: "Всего хостов", icon: Server, accent: "text-foreground" },
  { key: "online", label: "Online", icon: CheckCircle2, accent: "text-emerald-600 dark:text-emerald-400" },
  { key: "offline", label: "Offline", icon: XCircle, accent: "text-rose-600 dark:text-rose-400" },
  { key: "unknown", label: "Неизвестно", icon: HelpCircle, accent: "text-muted-foreground" },
];

export default function Dashboard() {
  const { theme } = useTheme();
  const { user } = useAuth();
  const canManage = user?.role === "admin" || user?.role === "operator";
  const [loading, setLoading] = useState(true);
  const [summary, setSummary] = useState<HostsSummary | null>(null);
  const [recentTasks, setRecentTasks] = useState<TaskRunOut[]>([]);
  const [topSoftware, setTopSoftware] = useState<SoftwareSummaryItem[]>([]);
  const [staleHosts, setStaleHosts] = useState<string[]>([]);
  const [recentChanges, setRecentChanges] = useState<SoftwareHistoryOut[]>([]);
  const [onlineTimeline, setOnlineTimeline] = useState<{ hour: string; online: number }[]>([]);
  const [weeklyStats, setWeeklyStats] = useState<{ day: string; success: number; failed: number }[]>([]);
  const [agentInstaller, setAgentInstaller] = useState<InstallerFile | null>(null);
  const [agentVersions, setAgentVersions] = useState<AgentVersionOverview | null>(null);
  const [syncingAgent, setSyncingAgent] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);

  const isDark = theme === "dark";
  const chart = {
    grid: isDark ? "#1e293b" : "#e2e8f0",
    tick: isDark ? "#94a3b8" : "#64748b",
    tooltip: {
      background: isDark ? "#0f172a" : "#ffffff",
      border: `1px solid ${isDark ? "#1e293b" : "#e2e8f0"}`,
      borderRadius: 8,
      fontSize: 12,
      color: isDark ? "#f1f5f9" : "#0f172a",
    },
    cursorFill: isDark ? "rgba(148, 163, 184, 0.08)" : "rgba(100, 116, 139, 0.08)",
    cursorStroke: isDark ? "#334155" : "#cbd5e1",
  };

  async function loadAgentInstaller() {
    const { data } = await apiClient.get<InstallerFile[]>("/installers");
    const installer = data.find((file) => file.name === AGENT_INSTALLER_NAME)
      ?? data.find((file) => /^FleetManagerAgent-Setup(?:[-_].+)?\.exe$/i.test(file.name));
    setAgentInstaller(installer ?? null);
  }

  async function loadAgentVersions() {
    const { data } = await apiClient.get<AgentVersionOverview>("/agent/versions");
    setAgentVersions(data);
  }

  useEffect(() => {
    setLoading(true);
    Promise.all([
      apiClient.get("/dashboard/hosts-summary").then((r) => setSummary(r.data)),
      apiClient.get("/dashboard/recent-tasks", { params: { limit: 8 } }).then((r) => setRecentTasks(r.data)),
      apiClient.get("/dashboard/top-software", { params: { limit: 8 } }).then((r) => setTopSoftware(r.data)),
      apiClient.get("/dashboard/stale-hosts", { params: { days: 7 } }).then((r) => setStaleHosts(r.data)),
      apiClient.get("/dashboard/recent-software-changes", { params: { limit: 8 } }).then((r) => setRecentChanges(r.data)),
      apiClient.get("/dashboard/online-timeline").then((r) => setOnlineTimeline(r.data)),
      apiClient.get("/dashboard/weekly-run-stats").then((r) => setWeeklyStats(r.data)),
      loadAgentInstaller(),
      loadAgentVersions(),
    ]).finally(() => setLoading(false));
  }, []);

  async function downloadAgent() {
    if (!agentInstaller) return;

    const token = getAccessToken();
    const response = await fetch(
      `${apiClient.defaults.baseURL}/installers/${encodeURIComponent(agentInstaller.name)}/download`,
      { headers: token ? { Authorization: `Bearer ${token}` } : {} },
    );
    if (!response.ok) return;

    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = agentInstaller.name;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function handleSyncAgent() {
    setSyncingAgent(true);
    setSyncMessage(null);
    try {
      const { data } = await apiClient.post<{ updated: boolean; version?: string; reason?: string }>(
        "/installers/agent/sync",
      );
      setSyncMessage(
        data.updated
          ? `Установщик агента обновлён до ${data.version}`
          : data.reason || "Обновлений не найдено",
      );
      if (data.updated) await Promise.all([loadAgentInstaller(), loadAgentVersions()]);
    } catch (e: any) {
      setSyncMessage(e.response?.data?.detail || "Не удалось проверить обновление агента");
    } finally {
      setSyncingAgent(false);
    }
  }

  return (
    <div className="animate-fade-in space-y-6">
      <div className="flex items-center justify-end gap-2">
        {syncMessage && <span className="text-sm text-muted-foreground">{syncMessage}</span>}
        {canManage && (
          <Button variant="secondary" size="sm" onClick={handleSyncAgent} loading={syncingAgent}>
            <RefreshCw className="h-3.5 w-3.5" />
            Проверить обновление агента
          </Button>
        )}
        <Button
          variant="secondary"
          size="sm"
          onClick={downloadAgent}
          disabled={!agentInstaller}
          title={agentInstaller ? `Скачать ${agentInstaller.name}` : "Установщик агента ещё не синхронизирован"}
        >
          <Download className="h-3.5 w-3.5" />
          Скачать агент
        </Button>
      </div>
      <h1 className="text-2xl font-semibold tracking-tight">Дашборд</h1>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {STAT_CARDS.map(({ key, label, icon: Icon, accent }) => (
          <Card key={key}>
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-medium text-muted-foreground">{label}</h2>
              <Icon className={`h-4 w-4 ${accent}`} />
            </div>
            <p className={`mt-2 text-3xl font-bold tabular-nums ${accent}`}>
              {loading
                ? <span className="inline-block h-8 w-12 animate-pulse rounded-md bg-muted" />
                : (summary?.[key] ?? "—")}
            </p>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Online хосты за последние 24 часа">
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={onlineTimeline}>
              <CartesianGrid strokeDasharray="3 3" stroke={chart.grid} />
              <XAxis dataKey="hour" tick={{ fontSize: 10, fill: chart.tick }} interval={3} />
              <YAxis tick={{ fontSize: 10, fill: chart.tick }} allowDecimals={false} />
              <Tooltip contentStyle={chart.tooltip} cursor={{ stroke: chart.cursorStroke }} />
              <Line type="monotone" dataKey="online" stroke="#3b82f6" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Запуски плейбуков за неделю">
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={weeklyStats}>
              <CartesianGrid strokeDasharray="3 3" stroke={chart.grid} />
              <XAxis dataKey="day" tick={{ fontSize: 10, fill: chart.tick }} />
              <YAxis tick={{ fontSize: 10, fill: chart.tick }} allowDecimals={false} />
              <Tooltip contentStyle={chart.tooltip} cursor={{ fill: chart.cursorFill }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="success" fill="#10b981" radius={[3, 3, 0, 0]} />
              <Bar dataKey="failed" fill="#f43f5e" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Последние запуски плейбуков">
          <ul className="space-y-2 text-sm">
            {recentTasks.map((t) => (
              <li key={t.id} className="flex items-center justify-between border-b border-border/70 pb-2 last:border-0 last:pb-0">
                <span className="truncate">{t.playbook_name || t.task_type}</span>
                <Badge status={t.status} />
              </li>
            ))}
            {recentTasks.length === 0 && <p className="text-subtle">Нет данных</p>}
          </ul>
        </Card>

        <Card title="Топ устанавливаемого ПО">
          <ul className="space-y-2 text-sm">
            {topSoftware.map((s, i) => (
              <li key={i} className="flex items-center justify-between border-b border-border/70 pb-2 last:border-0 last:pb-0">
                <span className="truncate">{s.name} {s.version && <span className="text-subtle">{s.version}</span>}</span>
                <span className="text-muted-foreground tabular-nums">{s.host_count} хост(ов)</span>
              </li>
            ))}
            {topSoftware.length === 0 && <p className="text-subtle">Нет данных</p>}
          </ul>
        </Card>

        <Card title={`Хосты без сканирования > 7 дней (${staleHosts.length})`}>
          <ul className="flex flex-wrap gap-2 text-sm">
            {staleHosts.map((h) => (
              <li key={h}>
                <Badge status="stale" tone="warning">{h}</Badge>
              </li>
            ))}
            {staleHosts.length === 0 && <p className="text-subtle">Все хосты просканированы недавно</p>}
          </ul>
        </Card>

        <Card title={`Версии агента (доступна ${agentVersions?.available_version ?? "—"})`}>
          <div className="flex flex-wrap gap-4 text-sm">
            <span className="text-emerald-600 dark:text-emerald-400">Актуальны: {agentVersions?.up_to_date ?? 0}</span>
            <span className="text-amber-600 dark:text-amber-400">Устарели: {agentVersions?.outdated ?? 0}</span>
            <span className="text-muted-foreground">Без данных: {agentVersions?.unknown ?? 0}</span>
            <span className="text-muted-foreground">Всего с агентом: {agentVersions?.total_agents ?? 0}</span>
          </div>
          <ul className="mt-3 space-y-2 text-sm">
            {agentVersions?.hosts
              .filter((h) => h.version_status === "outdated")
              .slice(0, 8)
              .map((h) => (
                <li key={h.host_id} className="flex items-center justify-between border-b border-border/70 pb-2 last:border-0 last:pb-0">
                  <span className="truncate">{h.hostname || h.host_id}</span>
                  <span className="font-mono text-muted-foreground">{h.agent_version ?? "—"}</span>
                </li>
              ))}
            {(agentVersions?.outdated ?? 0) === 0 && <p className="text-subtle">Устаревших агентов нет</p>}
          </ul>
        </Card>

        <Card title="Последние изменения в реестре ПО">
          <ul className="space-y-2 text-sm">
            {recentChanges.map((c) => (
              <li key={c.id} className="flex items-center justify-between border-b border-border/70 pb-2 last:border-0 last:pb-0">
                <span className="truncate">{c.name}</span>
                <span className="text-muted-foreground">
                  {c.change_type}: {c.old_version || "—"} → {c.new_version || "—"}
                </span>
              </li>
            ))}
            {recentChanges.length === 0 && <p className="text-subtle">Нет данных</p>}
          </ul>
        </Card>
      </div>
    </div>
  );
}
