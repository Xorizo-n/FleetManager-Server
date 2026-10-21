import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity, AlertTriangle, Bell, BellOff, CheckCircle2, Clock, Cpu, Gauge, HardDrive, History,
  MemoryStick, MonitorDot, Network, ServerCrash, Timer, Wifi,
} from "lucide-react";
import { apiClient } from "../api/client";

interface HostsSummary {
  total: number;
  online: number;
  offline: number;
  unknown: number;
}

interface AgentAlert {
  id: string;
  host_id: string;
  alert_type: string;
  message: string;
  created_at: string;
}

interface HostLite {
  id: string;
  hostname: string;
}

interface DiskUsage {
  mount: string;
  total_gb: number;
  used_gb: number;
  percent: number;
}

interface ServerMetrics {
  cpu_percent: number;
  cpu_count: number;
  load_avg: number[];
  mem_total_gb: number;
  mem_used_gb: number;
  mem_percent: number;
  swap_percent: number;
  net_sent_mbps: number;
  net_recv_mbps: number;
  disks: DiskUsage[];
  uptime_seconds: number;
  process_count: number;
}

interface TimelinePoint {
  hour: string;
  online: number;
}

interface RecentTask {
  id: string;
  task_type: string;
  playbook_name: string | null;
  host_ids: string[];
  status: string;
  created_at: string;
}

const TASK_TYPE_LABEL: Record<string, string> = {
  playbook: "Плейбук",
  software_scan: "Скан ПО",
  host_diagnostic: "Диагностика",
  agent_version_scan: "Версия агента",
  agent_update: "Обновление агента",
  access_change: "Смена доступа",
  host_wake: "Пробуждение",
};

const TASK_STATUS: Record<string, { label: string; dot: string; text: string; pulse?: boolean }> = {
  queued: { label: "в очереди", dot: "bg-slate-400", text: "text-muted-foreground" },
  running: { label: "выполняется", dot: "bg-blue-500", text: "text-blue-600 dark:text-blue-400", pulse: true },
  waiting: { label: "ждёт ПК", dot: "bg-amber-500", text: "text-amber-600 dark:text-amber-400" },
  success: { label: "успех", dot: "bg-emerald-500", text: "text-emerald-600 dark:text-emerald-400" },
  failed: { label: "ошибка", dot: "bg-rose-500", text: "text-rose-600 dark:text-rose-400" },
  cancelled: { label: "отменено", dot: "bg-slate-400", text: "text-muted-foreground" },
};

const ALERT_TYPE_LABEL: Record<string, string> = {
  disk_full: "Диск заполнен",
  hardware_changed: "Смена железа",
  agent_offline: "Агент офлайн",
};

function formatUptime(sec: number): string {
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (d > 0) return `${d} д ${h} ч`;
  if (h > 0) return `${h} ч ${m} мин`;
  return `${m} мин`;
}

function ago(iso: string, now: number): string {
  const s = Math.max(0, Math.floor((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s} с`;
  const mn = Math.floor(s / 60);
  if (mn < 60) return `${mn} мин`;
  const h = Math.floor(mn / 60);
  if (h < 24) return `${h} ч`;
  return `${Math.floor(h / 24)} д`;
}

function barTone(pct: number): string {
  if (pct >= 90) return "bg-rose-500";
  if (pct >= 75) return "bg-amber-500";
  return "bg-emerald-500";
}

function sparkTone(pct: number): string {
  if (pct >= 90) return "text-rose-500";
  if (pct >= 75) return "text-amber-500";
  return "text-emerald-500";
}

function Sparkline({ data, className = "text-blue-500", height = "h-6" }: { data: number[]; className?: string; height?: string }) {
  if (data.length < 2) return <div className={height} />;
  const w = 120;
  const h = 24;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - ((v - min) / range) * (h - 3) - 1.5}`);
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className={`${height} w-full ${className}`}>
      <polyline points={`0,${h} ${pts.join(" ")} ${w},${h}`} fill="currentColor" fillOpacity={0.08} stroke="none" />
      <polyline points={pts.join(" ")} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

const ALERT_WINDOW_MS = 24 * 60 * 60 * 1000; // «активными» считаем алерты за последние сутки

function useBeeper(active: boolean, enabled: boolean) {
  const ctxRef = useRef<AudioContext | null>(null);

  function beep() {
    try {
      if (!ctxRef.current) {
        const Ctor = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
        ctxRef.current = new Ctor();
      }
      const ctx = ctxRef.current;
      if (ctx.state === "suspended") void ctx.resume();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "square";
      osc.frequency.value = 880;
      const t = ctx.currentTime;
      gain.gain.setValueAtTime(0.0001, t);
      gain.gain.exponentialRampToValueAtTime(0.3, t + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.4);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(t);
      osc.stop(t + 0.42);
    } catch {
      /* звук недоступен — не критично */
    }
  }

  useEffect(() => {
    if (!active || !enabled) return;
    beep();
    const id = window.setInterval(beep, 2500);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, enabled]);

  // Возвращаем ручной «пинок» для разблокировки звука по клику пользователя
  return () => {
    if (ctxRef.current?.state === "suspended") void ctxRef.current.resume();
    beep();
  };
}

const TONE_TEXT = {
  ok: "text-emerald-600 dark:text-emerald-400",
  warn: "text-amber-600 dark:text-amber-400",
  bad: "text-rose-600 dark:text-rose-400",
  neutral: "text-foreground",
} as const;

type Tone = keyof typeof TONE_TEXT;

function Stat({ icon, label, value, tone }: { icon: React.ReactNode; label: string; value: number | string; tone: Tone }) {
  return (
    <div className="surface-card flex items-center gap-2.5 p-2.5">
      <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted ${TONE_TEXT[tone]}`}>{icon}</span>
      <div className="min-w-0">
        <div className={`text-2xl font-bold leading-none tabular-nums ${TONE_TEXT[tone]}`}>{value}</div>
        <div className="mt-1 truncate text-xs text-muted-foreground">{label}</div>
      </div>
    </div>
  );
}

function MetricBar({ icon, label, pct, detail, spark, sparkClass }: {
  icon: React.ReactNode; label: string; pct: number; detail: string; spark?: number[]; sparkClass?: string;
}) {
  return (
    <div className="surface-card flex flex-col justify-center p-2.5">
      <div className="mb-1 flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-xs font-medium text-foreground">
          <span className="text-blue-600 dark:text-blue-400">{icon}</span>
          {label}
        </span>
        <span className="text-sm font-semibold tabular-nums text-foreground">{Math.round(pct)}%</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div className={`h-full rounded-full transition-all duration-500 ${barTone(pct)}`} style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
      </div>
      {spark && <Sparkline data={spark} className={sparkClass} />}
      <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{detail}</div>
    </div>
  );
}

export default function Monitoring() {
  const [soundOn, setSoundOn] = useState(true);
  const [now, setNow] = useState(Date.now());

  const summary = useQuery({
    queryKey: ["mon", "hosts-summary"],
    queryFn: () => apiClient.get<HostsSummary>("/dashboard/hosts-summary").then((r) => r.data),
    refetchInterval: 15000,
  });
  const hosts = useQuery({
    queryKey: ["mon", "hosts"],
    queryFn: () => apiClient.get<HostLite[]>("/hosts").then((r) => r.data),
    refetchInterval: 60000,
  });
  const alerts = useQuery({
    queryKey: ["mon", "alerts"],
    queryFn: () => apiClient.get<AgentAlert[]>("/agent/alerts", { params: { limit: 100 } }).then((r) => r.data),
    refetchInterval: 15000,
  });
  const metrics = useQuery({
    queryKey: ["mon", "server-metrics"],
    queryFn: () => apiClient.get<ServerMetrics>("/dashboard/server-metrics").then((r) => r.data),
    refetchInterval: 5000,
  });
  const timeline = useQuery({
    queryKey: ["mon", "online-timeline"],
    queryFn: () => apiClient.get<TimelinePoint[]>("/dashboard/online-timeline").then((r) => r.data),
    refetchInterval: 60000,
  });
  const stale = useQuery({
    queryKey: ["mon", "stale-hosts"],
    queryFn: () => apiClient.get<string[]>("/dashboard/stale-hosts").then((r) => r.data),
    refetchInterval: 60000,
  });
  const recentTasks = useQuery({
    queryKey: ["mon", "recent-tasks"],
    queryFn: () => apiClient.get<RecentTask[]>("/dashboard/recent-tasks", { params: { limit: 8 } }).then((r) => r.data),
    refetchInterval: 10000,
  });

  // пересчитываем «свежесть» алертов и относительное время каждые 15с
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 15000);
    return () => window.clearInterval(id);
  }, []);

  const m = metrics.data;
  // Копим короткую историю метрик на клиенте (опрос раз в 5с) для живых спарклайнов
  const [cpuHist, setCpuHist] = useState<number[]>([]);
  const [netHist, setNetHist] = useState<number[]>([]);
  useEffect(() => {
    if (!m) return;
    setCpuHist((h) => [...h, m.cpu_percent].slice(-60));
    setNetHist((h) => [...h, m.net_recv_mbps + m.net_sent_mbps].slice(-60));
  }, [m]);

  const hostName = useMemo(() => {
    const map = new Map<string, string>();
    (hosts.data ?? []).forEach((h) => map.set(h.id, h.hostname));
    return map;
  }, [hosts.data]);

  const activeAlerts = useMemo(
    () => (alerts.data ?? []).filter((a) => now - new Date(a.created_at).getTime() <= ALERT_WINDOW_MS),
    [alerts.data, now],
  );
  const hasAlerts = activeAlerts.length > 0;

  // Разбивка активных алертов по типам — компактные чипы над списком
  const alertsByType = useMemo(() => {
    const map = new Map<string, number>();
    activeAlerts.forEach((a) => map.set(a.alert_type, (map.get(a.alert_type) ?? 0) + 1));
    return [...map.entries()].sort((a, b) => b[1] - a[1]);
  }, [activeAlerts]);

  // Принятые алерты: по ним звук больше не пищит. Храним id в localStorage, чтобы
  // перезагрузка страницы не включала сигнал заново по уже увиденным алертам.
  const [acked, setAcked] = useState<Set<string>>(() => {
    try {
      return new Set<string>(JSON.parse(localStorage.getItem("mon.acked") || "[]"));
    } catch {
      return new Set<string>();
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem("mon.acked", JSON.stringify([...acked]));
    } catch {
      /* localStorage недоступен — не критично */
    }
  }, [acked]);

  const unacked = useMemo(() => activeAlerts.filter((a) => !acked.has(a.id)), [activeAlerts, acked]);

  function acknowledgeAll() {
    setAcked(new Set(activeAlerts.map((a) => a.id)));
  }

  // Звук — только пока есть НОВЫЕ (непринятые) алерты. Новый алерт снова включит сигнал.
  const kick = useBeeper(unacked.length > 0, soundOn);

  const s = summary.data;
  const onlinePct = s && s.total > 0 ? Math.round((s.online / s.total) * 100) : null;
  const timelineData = (timeline.data ?? []).map((p) => p.online);

  return (
    // Настенный дисплей: занимает всю высоту под шапкой приложения (3.5rem), без скролла.
    // 100vh (а не dvh) — у ТВ нет динамических панелей, зато старые webkit-браузеры ТВ знают только vh.
    <div className="flex h-[calc(100vh-3.5rem)] flex-col gap-2.5 overflow-hidden p-3 sm:p-4">
      {/* Заголовок */}
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <div className="flex items-center gap-2">
            <MonitorDot className="h-6 w-6 text-blue-600 dark:text-blue-400" />
            <h1 className="text-xl font-semibold tracking-tight">Мониторинг инфраструктуры</h1>
          </div>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-600 dark:text-emerald-400">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" /> в реальном времени
          </span>
          {m && (
            <span className="inline-flex items-center gap-3 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1"><Timer className="h-3.5 w-3.5" /> аптайм {formatUptime(m.uptime_seconds)}</span>
              <span className="inline-flex items-center gap-1"><History className="h-3.5 w-3.5" /> {m.process_count} проц.</span>
            </span>
          )}
        </div>
        <button
          onClick={() => {
            setSoundOn((v) => !v);
            kick();
          }}
          className={`inline-flex items-center gap-2 rounded-xl px-3 py-1.5 text-sm font-medium transition-colors ${
            soundOn ? "bg-blue-500/10 text-blue-600 dark:text-blue-400" : "bg-muted text-muted-foreground"
          }`}
          title="Звуковое оповещение об алертах"
        >
          {soundOn ? <Bell className="h-4 w-4" /> : <BellOff className="h-4 w-4" />}
          Звук {soundOn ? "вкл" : "выкл"}
        </button>
      </div>

      {/* Компактная строка ключевых показателей */}
      <div className="grid shrink-0 grid-cols-3 gap-2.5 sm:grid-cols-6">
        <Stat icon={<Wifi className="h-5 w-5" />} label="Онлайн" value={s?.online ?? "—"} tone="ok" />
        <Stat icon={<ServerCrash className="h-5 w-5" />} label="Офлайн" value={s?.offline ?? "—"} tone={s && s.offline > 0 ? "bad" : "neutral"} />
        <Stat icon={<Gauge className="h-5 w-5" />} label="Доступность" value={onlinePct !== null ? `${onlinePct}%` : "—"} tone={onlinePct !== null && onlinePct < 90 ? "warn" : "ok"} />
        <Stat icon={<MonitorDot className="h-5 w-5" />} label="Всего хостов" value={s?.total ?? "—"} tone="neutral" />
        <Stat icon={<AlertTriangle className="h-5 w-5" />} label="Алертов за 24ч" value={activeAlerts.length} tone={hasAlerts ? "bad" : "ok"} />
        <Stat icon={<Clock className="h-5 w-5" />} label="Не на связи >7д" value={stale.data?.length ?? "—"} tone={stale.data && stale.data.length > 0 ? "warn" : "neutral"} />
      </div>

      {/* Метрики сервера — одна компактная полоса */}
      <div className="grid shrink-0 grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
        {m ? (
          <>
            <MetricBar icon={<Cpu className="h-3.5 w-3.5" />} label="CPU" pct={m.cpu_percent} spark={cpuHist} sparkClass={sparkTone(m.cpu_percent)}
              detail={`${m.cpu_count} ядер${m.load_avg.length ? ` · load ${m.load_avg.map((x) => x.toFixed(1)).join("/")}` : ""}`} />
            <MetricBar icon={<MemoryStick className="h-3.5 w-3.5" />} label="Память" pct={m.mem_percent}
              detail={`${m.mem_used_gb}/${m.mem_total_gb} ГБ${m.swap_percent > 0 ? ` · swap ${Math.round(m.swap_percent)}%` : ""}`} />
            <div className="surface-card flex flex-col justify-center p-2.5">
              <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-foreground">
                <span className="text-blue-600 dark:text-blue-400"><Network className="h-3.5 w-3.5" /></span>Сеть
              </div>
              <Sparkline data={netHist} className="text-blue-500" />
              <div className="mt-0.5 flex items-center justify-between gap-1 text-[11px]">
                <span className="font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">↓{m.net_recv_mbps.toFixed(1)}</span>
                <span className="font-semibold tabular-nums text-blue-600 dark:text-blue-400">↑{m.net_sent_mbps.toFixed(1)} Мбит/с</span>
              </div>
            </div>
            {m.disks.map((d) => (
              <MetricBar key={d.mount} icon={<HardDrive className="h-3.5 w-3.5" />} label={`Диск ${d.mount === "/" ? "сист." : d.mount}`} pct={d.percent}
                detail={`${d.used_gb}/${d.total_gb} ГБ · своб. ${(d.total_gb - d.used_gb).toFixed(0)}`} />
            ))}
            <div className="surface-card flex flex-col justify-center p-2.5">
              <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-foreground">
                <span className="text-blue-600 dark:text-blue-400"><Wifi className="h-3.5 w-3.5" /></span>Онлайн 24ч
              </div>
              <Sparkline data={timelineData} className="text-blue-500" />
              <div className="mt-0.5 truncate text-[11px] text-muted-foreground tabular-nums">
                {timelineData.length > 0 ? `макс ${Math.max(...timelineData)} · сейчас ${timelineData[timelineData.length - 1]}` : "нет данных"}
              </div>
            </div>
          </>
        ) : (
          <div className="surface-card col-span-full p-3 text-center text-sm text-muted-foreground">
            {metrics.isError ? "Метрики сервера недоступны" : "Загрузка метрик..."}
          </div>
        )}
      </div>

      {/* Растягивающаяся область: алерты (крупно) + последние задачи */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-2.5 lg:grid-cols-3">
        {/* Алерты */}
        {hasAlerts ? (
          <div className="flex min-h-0 flex-col rounded-2xl border-2 border-rose-500/70 bg-rose-500/5 p-3 shadow-panel-lg lg:col-span-2">
            <div className="mb-2 flex shrink-0 flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2.5">
                <AlertTriangle className={`h-6 w-6 text-rose-600 dark:text-rose-400 ${unacked.length > 0 ? "animate-pulse" : ""}`} />
                <h2 className="text-lg font-bold text-rose-600 dark:text-rose-400">
                  {activeAlerts.length} {activeAlerts.length === 1 ? "активный алерт" : "активных алертов"}
                  {unacked.length > 0 && <span className="ml-2 text-sm font-semibold">· {unacked.length} новых</span>}
                </h2>
              </div>
              {unacked.length > 0 && (
                <button
                  onClick={acknowledgeAll}
                  className="inline-flex items-center gap-2 rounded-xl bg-rose-600 px-3 py-1.5 text-sm font-semibold text-white transition-colors hover:bg-rose-700"
                  title="Заглушить звук по текущим алертам (новый алерт снова включит сигнал)"
                >
                  <BellOff className="h-4 w-4" /> Принять ({unacked.length})
                </button>
              )}
            </div>
            {/* Разбивка по типам */}
            <div className="mb-2 flex shrink-0 flex-wrap gap-1.5">
              {alertsByType.map(([type, count]) => (
                <span key={type} className="inline-flex items-center gap-1.5 rounded-lg bg-rose-500/15 px-2 py-0.5 text-xs font-semibold text-rose-600 dark:text-rose-400">
                  {ALERT_TYPE_LABEL[type] ?? type}
                  <span className="rounded bg-rose-600/90 px-1.5 text-white">{count}</span>
                </span>
              ))}
            </div>
            {/* Список — заполняет оставшуюся высоту, лишнее обрезается (без скролла на ТВ) */}
            <div className="min-h-0 flex-1 space-y-1.5 overflow-hidden">
              {activeAlerts.map((a) => (
                <div key={a.id} className="rounded-xl border border-rose-500/40 bg-background/60 px-3 py-2">
                  <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-0.5">
                    <span className="flex items-center gap-2 font-bold text-rose-600 dark:text-rose-400">
                      {hostName.get(a.host_id) ?? a.host_id.slice(0, 8)}
                      {!acked.has(a.id) && <span className="rounded bg-rose-600 px-1.5 py-0.5 text-[10px] font-bold uppercase text-white">новый</span>}
                    </span>
                    <span className="rounded-md bg-rose-500/15 px-2 py-0.5 text-xs font-semibold text-rose-600 dark:text-rose-400">
                      {ALERT_TYPE_LABEL[a.alert_type] ?? a.alert_type}
                    </span>
                    <span className="text-xs text-muted-foreground">{new Date(a.created_at).toLocaleString()}</span>
                  </div>
                  <p className="mt-0.5 truncate text-sm text-foreground">{a.message}</p>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="surface-card flex min-h-0 flex-col items-center justify-center gap-3 p-6 text-center lg:col-span-2">
            <CheckCircle2 className="h-16 w-16 text-emerald-500" />
            <p className="text-2xl font-semibold text-foreground">Всё спокойно</p>
            <p className="text-muted-foreground">Активных алертов за последние 24 часа нет.</p>
          </div>
        )}

        {/* Последние задачи */}
        <div className="surface-card flex min-h-0 flex-col p-3">
          <div className="mb-2 flex shrink-0 items-center gap-1.5 text-sm font-medium text-foreground">
            <Activity className="h-4 w-4 text-blue-600 dark:text-blue-400" /> Последние задачи
          </div>
          <div className="min-h-0 flex-1 space-y-0.5 overflow-hidden">
            {(recentTasks.data ?? []).length === 0 && (
              <p className="py-3 text-center text-sm text-muted-foreground">Задач пока нет</p>
            )}
            {(recentTasks.data ?? []).map((t) => {
              const st = TASK_STATUS[t.status] ?? { label: t.status, dot: "bg-slate-400", text: "text-muted-foreground" };
              return (
                <div key={t.id} className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm odd:bg-muted/40">
                  <span className={`h-2 w-2 shrink-0 rounded-full ${st.dot} ${st.pulse ? "animate-pulse" : ""}`} />
                  <span className="min-w-0 flex-1 truncate text-foreground" title={t.playbook_name ?? undefined}>
                    {t.playbook_name ?? `${t.host_ids.length} ПК`}
                    <span className="ml-1 text-xs text-muted-foreground">· {TASK_TYPE_LABEL[t.task_type] ?? t.task_type}</span>
                  </span>
                  <span className={`shrink-0 text-xs font-medium ${st.text}`}>{st.label}</span>
                  <span className="w-12 shrink-0 text-right text-xs text-subtle tabular-nums">{ago(t.created_at, now)}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
