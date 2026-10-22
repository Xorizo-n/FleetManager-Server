import { ReactNode, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity, AlertCircle, AlertTriangle, ArrowUpCircle, Bell, BellOff, Building2, CheckCircle2, Cpu, HardDrive, Info,
  KeyRound, MemoryStick, MonitorDot, Network, OctagonAlert, Server, ServerOff, ShieldAlert, Wifi, WifiOff,
} from "lucide-react";
import { apiClient } from "../api/client";
import type { TaskRun } from "../api/types";
import { APP_TIME_ZONE, pcCount, taskTitle } from "../lib/format";

// ---------------------------------------------------------------------------
// Данные
// ---------------------------------------------------------------------------

interface Room {
  id: string;
  name: string;
  short_name: string;
  total: number;
  online: number;
  alerts: number;
  disk: number;
  not_activated: number;
}

interface Building {
  id: string;
  name: string;
  total: number;
  online: number;
  floors: { name: string | null; rooms: Room[] }[];
}

interface MonAlert {
  id: string;
  host_id: string;
  hostname: string | null;
  room: string | null;
  alert_type: string;
  message: string;
  created_at: string;
}

interface Summary {
  generated_at: string;
  total: number;
  online: number;
  offline: number;
  unknown: number;
  stale_7d: number;
  without_agent: number;
  agent_available_version: string | null;
  agent_outdated: number;
  win_not_activated: number;
  office_not_activated: number;
  kms_unreachable: number;
  disks_critical: number;
  tasks_running: number;
  tasks_failed_24h: number;
  alerts_24h: number;
  alerts: MonAlert[];
  buildings: Building[];
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
  disks: { mount: string; total_gb: number; used_gb: number; percent: number }[];
  uptime_seconds: number;
}

// ---------------------------------------------------------------------------
// Серьёзность. Красный — только беда самого сервера или потеря связи с ним:
// один выключенный ПК или один полный диск в аудитории аварией экрана не считается.
// ---------------------------------------------------------------------------

type Sev = "critical" | "serious" | "warning" | "info";

const SEV_RANK: Record<Sev, number> = { critical: 0, serious: 1, warning: 2, info: 3 };

const SEV: Record<Sev, { label: string; icon: typeof Info; text: string; chip: string }> = {
  critical: { label: "критично", icon: OctagonAlert, text: "text-rose-600 dark:text-rose-400", chip: "bg-rose-600 text-white" },
  serious: { label: "серьёзно", icon: AlertTriangle, text: "text-orange-600 dark:text-orange-400", chip: "bg-orange-500/15 text-orange-700 dark:text-orange-300" },
  warning: { label: "внимание", icon: AlertCircle, text: "text-amber-600 dark:text-amber-400", chip: "bg-amber-500/15 text-amber-700 dark:text-amber-300" },
  info: { label: "инфо", icon: Info, text: "text-sky-600 dark:text-sky-400", chip: "bg-sky-500/15 text-sky-700 dark:text-sky-300" },
};

const ALERT_TYPE: Record<string, { label: string; sev: Sev }> = {
  disk_full: { label: "Диск заполнен", sev: "serious" },
  hardware_changed: { label: "Смена железа", sev: "serious" },
  device_missing: { label: "Пропало устройство", sev: "warning" },
  agent_offline: { label: "Агент офлайн", sev: "warning" },
};

const TASK_STATUS: Record<string, { label: string; dot: string; text: string; pulse?: boolean }> = {
  queued: { label: "в очереди", dot: "bg-slate-400", text: "text-muted-foreground" },
  running: { label: "идёт", dot: "bg-blue-500", text: "text-blue-600 dark:text-blue-400", pulse: true },
  waiting: { label: "ждёт ПК", dot: "bg-amber-500", text: "text-amber-600 dark:text-amber-400" },
  success: { label: "успех", dot: "bg-emerald-500", text: "text-emerald-600 dark:text-emerald-400" },
  failed: { label: "ошибка", dot: "bg-rose-500", text: "text-rose-600 dark:text-rose-400" },
  cancelled: { label: "отменена", dot: "bg-slate-400", text: "text-muted-foreground" },
};

interface Problem {
  key: string;
  sev: Sev;
  title: string;
  detail: string;
  at?: string;
  isNew?: boolean;
  /** Сколько ПК затронуто: при равной серьёзности выше то, что задевает больше машин */
  weight?: number;
}

/** Аудитория с отклонением: часть ПК выпала при работающих остальных, алерты или полный диск.
 *  Полностью выключенная аудитория — норма (в ней нет занятий), отклонением не считается. */
interface Deviation extends Room {
  where: string;
  missing: number;
}

const ALERT_WINDOW_MS = 24 * 60 * 60 * 1000;
const STALE_MS = 60_000; // данные старше минуты — экран «не знает», что происходит
const PROBLEM_ROW_PX = 44;
const DEVIATION_ROW_PX = 36;
const TASK_ROWS = 4;
// На невысоком экране (ноутбук 1366×768) второстепенное прячем, отдавая высоту спискам.
// Строка целиком — чтобы Tailwind увидел класс при сборке.
const SHORT_HIDE = "[@media(max-height:820px)]:hidden";

// ---------------------------------------------------------------------------
// Утилиты
// ---------------------------------------------------------------------------

function formatUptime(sec: number): string {
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (d > 0) return `${d} д ${h} ч`;
  if (h > 0) return `${h} ч ${m} мин`;
  return `${m} мин`;
}

function ago(iso: string | number, now: number): string {
  const t = typeof iso === "number" ? iso : new Date(iso).getTime();
  const s = Math.max(0, Math.floor((now - t) / 1000));
  if (s < 60) return `${s} с`;
  const mn = Math.floor(s / 60);
  if (mn < 60) return `${mn} мин`;
  const h = Math.floor(mn / 60);
  if (h < 24) return `${h} ч`;
  return `${Math.floor(h / 24)} д`;
}

const pct = (n: number, total: number) => (total > 0 ? Math.round((n / total) * 100) : 0);

function loadTone(p: number): { bar: string; text: string } {
  if (p >= 90) return { bar: "bg-rose-500", text: "text-rose-500" };
  if (p >= 75) return { bar: "bg-amber-500", text: "text-amber-500" };
  return { bar: "bg-emerald-500", text: "text-emerald-500" };
}

const floorLabel = (name: string | null) => (name ? name.replace(/\s*этаж\s*/i, " эт.").trim() : null);

/**
 * Сколько строк фиксированной высоты помещается в контейнер. Экран ТВ не прокручивается,
 * а разрешение заранее неизвестно, поэтому списки показывают ровно столько, сколько влезает,
 * а остаток сворачивают в «и ещё N» — без строк, обрезанных посередине.
 */
function useRowCapacity<T extends HTMLElement>(rowPx: number) {
  const ref = useRef<T>(null);
  const [rows, setRows] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setRows(Math.max(0, Math.floor(el.clientHeight / rowPx)));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [rowPx]);
  return [ref, rows] as const;
}

/** Первые элементы под ёмкость; если всё не влезло, последнее место отдаётся под «и ещё N» */
function fit<T>(items: T[], capacity: number): { shown: T[]; hidden: number } {
  if (items.length <= capacity) return { shown: items, hidden: 0 };
  const shown = items.slice(0, Math.max(0, capacity - 1));
  return { shown, hidden: items.length - shown.length };
}

/**
 * ТВ мониторинга никто не перезагружает руками, а одностраничное приложение само
 * не обновляется: после деплоя экран продолжал крутить старый код (так он показывал
 * московское время уже после исправления). Раз в пару минут сверяем, какой бандл
 * сейчас отдаёт сервер, и при смене перезагружаем страницу.
 */
function useReloadOnNewVersion(intervalMs = 120_000) {
  useEffect(() => {
    const bundle = /\/assets\/index-[^"'/]+\.js/;
    const loaded = Array.from(document.scripts).map((s) => s.src).find((src) => bundle.test(src));
    if (!loaded) return; // dev-сервер: собранного бандла нет
    const mine = new URL(loaded).pathname;
    const id = window.setInterval(async () => {
      try {
        const html = await fetch("/index.html", { cache: "no-store" }).then((r) => r.text());
        const current = html.match(bundle)?.[0];
        if (current && current !== mine) window.location.reload();
      } catch {
        /* сервер недоступен — проверим в следующий раз */
      }
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
}

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

  // Ручной «пинок» — браузер разрешает звук только после клика пользователя
  return () => {
    if (ctxRef.current?.state === "suspended") void ctxRef.current.resume();
    beep();
  };
}

// ---------------------------------------------------------------------------
// Мелкие компоненты
// ---------------------------------------------------------------------------

/** Спарклайн: заливка + линия 2px + выделенная последняя точка */
function Sparkline({ data, className = "text-blue-500" }: { data: number[]; className?: string }) {
  if (data.length < 2) return <div className="h-6" />;
  const w = 120;
  const h = 24;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const ys = data.map((v) => h - 2 - ((v - min) / range) * (h - 4));
  const pts = ys.map((y, i) => `${(i / (data.length - 1)) * w},${y}`).join(" ");
  const last = ys[ys.length - 1] / h;
  return (
    <div className={`relative h-6 w-full ${className}`}>
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="absolute inset-0 h-full w-full overflow-visible" aria-hidden="true">
        <polygon points={`0,${h} ${pts} ${w},${h}`} fill="currentColor" fillOpacity={0.12} />
        <polyline points={pts} fill="none" stroke="currentColor" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      </svg>
      <span className="absolute h-1.5 w-1.5 rounded-full bg-current ring-2 ring-surface" style={{ right: -3, top: `calc(${last * 100}% - 3px)` }} />
    </div>
  );
}

/** Часы отдельным компонентом: тикают раз в секунду, не перерисовывая весь экран */
function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);
  // Пояс задан явно: ТВ может стоять с другим поясом в ОС (было московское время вместо Екб)
  const time = now.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: APP_TIME_ZONE });
  const date = now.toLocaleDateString("ru-RU", { weekday: "long", day: "numeric", month: "long", timeZone: APP_TIME_ZONE });
  return (
    <div className="text-right leading-tight">
      <div className="text-2xl font-semibold tabular-nums text-foreground">{time}</div>
      <div className="text-xs capitalize text-muted-foreground">{date}</div>
    </div>
  );
}

function UpdatedAgo({ at }: { at: number }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  if (!at) return null;
  return <span className="hidden text-xs tabular-nums text-muted-foreground lg:inline">обновлено {ago(at, now)} назад</span>;
}

type KpiTone = "good" | "neutral" | Sev;

const KPI_TONE: Record<KpiTone, string> = {
  good: "text-emerald-600 dark:text-emerald-400",
  neutral: "text-foreground",
  critical: SEV.critical.text,
  serious: SEV.serious.text,
  warning: SEV.warning.text,
  info: SEV.info.text,
};

function Kpi({ icon, label, value, suffix, sub, tone, meter }: {
  icon: ReactNode; label: string; value: ReactNode; suffix?: string; sub: string; tone: KpiTone; meter?: number;
}) {
  return (
    <div className="surface-card flex min-w-0 flex-col p-3">
      <div className="flex items-start justify-between gap-1.5">
        {/* Подпись в две строки, а не обрезанная: на узком экране «Windows без активации» не влезает в одну */}
        <span className="line-clamp-2 min-h-[2rem] text-xs font-medium leading-4 text-muted-foreground">{label}</span>
        <span className={`shrink-0 ${tone === "neutral" ? "text-muted-foreground" : KPI_TONE[tone]}`}>{icon}</span>
      </div>
      <div className="mt-1 flex items-baseline gap-1">
        <span className={`text-3xl font-bold leading-none tabular-nums ${KPI_TONE[tone]}`}>{value}</span>
        {suffix && <span className="text-sm tabular-nums text-muted-foreground">{suffix}</span>}
      </div>
      <div className="mt-1 truncate text-[11px] text-muted-foreground" title={sub}>{sub}</div>
      {meter !== undefined && (
        <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-muted">
          <div className="h-full rounded-full bg-emerald-500 transition-all duration-500" style={{ width: `${meter}%` }} />
        </div>
      )}
    </div>
  );
}

/** Корпус: сколько ПК в сети и где отклонения — без перечисления всех аудиторий */
function BuildingCard({ b, deviating }: { b: Building; deviating: number }) {
  const rooms = b.floors.flatMap((f) => f.rooms);
  const share = pct(b.online, b.total);
  const alerts = rooms.reduce((n, r) => n + r.alerts, 0);
  const disks = rooms.reduce((n, r) => n + r.disk, 0);
  const dark = rooms.filter((r) => r.online === 0).length;
  return (
    <div className="surface-card flex min-w-0 flex-col p-3">
      <div className="flex items-center gap-2">
        <Building2 className="h-4 w-4 shrink-0 text-blue-600 dark:text-blue-400" />
        <span className="truncate text-base font-semibold text-foreground">{b.name}</span>
        <span className="ml-auto shrink-0 text-xs tabular-nums text-muted-foreground">{rooms.length} ауд.</span>
      </div>
      <div className="mt-1.5 flex items-baseline gap-1">
        <span className="text-2xl font-bold leading-none tabular-nums text-foreground" title="ПК в сети">{b.online}</span>
        <span className="text-sm tabular-nums text-muted-foreground">/ {b.total}</span>
        <span className="ml-auto text-sm font-semibold tabular-nums text-foreground">{share}%</span>
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-blue-600 transition-all duration-500" style={{ width: `${share}%` }} />
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
        {deviating > 0 ? (
          <span className="flex items-center gap-1 text-amber-700 dark:text-amber-300"><AlertCircle className="h-3.5 w-3.5" />{deviating} с отклонениями</span>
        ) : (
          <span className="flex items-center gap-1 text-emerald-700 dark:text-emerald-300"><CheckCircle2 className="h-3.5 w-3.5" />без отклонений</span>
        )}
        {alerts > 0 && <span className="flex items-center gap-1 text-rose-700 dark:text-rose-300"><Bell className="h-3.5 w-3.5" />{alerts}</span>}
        {disks > 0 && <span className="flex items-center gap-1 text-orange-700 dark:text-orange-300"><HardDrive className="h-3.5 w-3.5" />{disks}</span>}
        {dark > 0 && <span>выкл. {dark}</span>}
      </div>
    </div>
  );
}

function MetricCell({ icon, label, value, pctValue, detail, spark, sparkClass }: {
  icon: ReactNode; label: string; value: string; pctValue?: number; detail: string; spark?: number[]; sparkClass?: string;
}) {
  const tone = pctValue !== undefined ? loadTone(pctValue) : null;
  return (
    <div className="surface-card flex min-w-0 flex-col justify-center gap-1 p-2.5">
      <div className="flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-1.5 text-xs font-medium text-foreground">
          <span className="shrink-0 text-blue-600 dark:text-blue-400">{icon}</span>
          <span className="truncate">{label}</span>
        </span>
        <span className="shrink-0 text-sm font-semibold tabular-nums text-foreground">{value}</span>
      </div>
      {tone && (
        <div className="h-1.5 overflow-hidden rounded-full bg-muted">
          <div className={`h-full rounded-full transition-all duration-500 ${tone.bar}`} style={{ width: `${Math.min(100, Math.max(0, pctValue ?? 0))}%` }} />
        </div>
      )}
      {spark && (
        <div className={SHORT_HIDE}>
          <Sparkline data={spark} className={sparkClass} />
        </div>
      )}
      <div className={`truncate text-[11px] text-muted-foreground ${SHORT_HIDE}`} title={detail}>{detail}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Страница
// ---------------------------------------------------------------------------

export default function Monitoring() {
  const [soundOn, setSoundOn] = useState(true);
  const [now, setNow] = useState(Date.now());

  const summary = useQuery({
    queryKey: ["mon", "summary"],
    queryFn: () => apiClient.get<Summary>("/dashboard/monitoring").then((r) => r.data),
    refetchInterval: 15_000,
  });
  const metrics = useQuery({
    queryKey: ["mon", "server-metrics"],
    queryFn: () => apiClient.get<ServerMetrics>("/dashboard/server-metrics").then((r) => r.data),
    refetchInterval: 5_000,
  });
  const timeline = useQuery({
    queryKey: ["mon", "online-timeline"],
    queryFn: () => apiClient.get<{ hour: string; online: number }[]>("/dashboard/online-timeline").then((r) => r.data),
    refetchInterval: 60_000,
  });
  const recentTasks = useQuery({
    queryKey: ["mon", "recent-tasks"],
    queryFn: () => apiClient.get<TaskRun[]>("/dashboard/recent-tasks", { params: { limit: TASK_ROWS } }).then((r) => r.data),
    refetchInterval: 10_000,
  });

  // «Свежесть» алертов и относительное время
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 15_000);
    return () => window.clearInterval(id);
  }, []);

  const s = summary.data;
  const m = metrics.data;

  // Короткая история метрик сервера на клиенте (опрос раз в 5 с) для живых спарклайнов
  const [cpuHist, setCpuHist] = useState<number[]>([]);
  const [netHist, setNetHist] = useState<number[]>([]);
  useEffect(() => {
    if (!m) return;
    setCpuHist((h) => [...h, m.cpu_percent].slice(-60));
    setNetHist((h) => [...h, m.net_recv_mbps + m.net_sent_mbps].slice(-60));
  }, [m]);

  const activeAlerts = useMemo(
    () => (s?.alerts ?? []).filter((a) => now - new Date(a.created_at).getTime() <= ALERT_WINDOW_MS),
    [s, now],
  );

  // Принятые алерты: по ним звук больше не пищит. В localStorage — чтобы перезагрузка
  // страницы не включала сигнал заново по уже увиденному.
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
  const kick = useBeeper(unacked.length > 0, soundOn);
  useReloadOnNewVersion();

  const stale = summary.isError || (summary.dataUpdatedAt > 0 && Date.now() - summary.dataUpdatedAt > STALE_MS);

  // Аудитории с отклонениями — показываем исключения, а не всё подряд
  const deviations = useMemo<Deviation[]>(() => {
    const list: Deviation[] = [];
    for (const b of s?.buildings ?? []) {
      for (const f of b.floors) {
        for (const r of f.rooms) {
          const missing = r.online > 0 ? r.total - r.online : 0;
          if (missing > 0 || r.alerts > 0 || r.disk > 0) {
            const floor = floorLabel(f.name);
            list.push({ ...r, missing, where: floor ? `${b.name} · ${floor}` : b.name });
          }
        }
      }
    }
    // Острое (алерты, диск) — выше; дальше — где выпало больше машин
    return list.sort((x, y) => y.alerts + y.disk - (x.alerts + x.disk) || y.missing - x.missing || x.name.localeCompare(y.name));
  }, [s]);
  const deviatingByBuilding = useMemo(() => {
    const map = new Map<string, number>();
    for (const b of s?.buildings ?? []) {
      const ids = new Set(b.floors.flatMap((f) => f.rooms.map((r) => r.id)));
      map.set(b.id, deviations.filter((d) => ids.has(d.id)).length);
    }
    return map;
  }, [s, deviations]);

  // Единый список проблем по серьёзности — как Problems в Zabbix
  const problems = useMemo<Problem[]>(() => {
    const list: Problem[] = [];
    if (stale) list.push({ key: "stale", sev: "critical", title: "Нет связи с сервером Fleet Manager", detail: "данные на экране могут быть устаревшими" });
    if (m) {
      const hot = [
        m.cpu_percent >= 90 ? `CPU ${Math.round(m.cpu_percent)}%` : null,
        m.mem_percent >= 90 ? `память ${Math.round(m.mem_percent)}%` : null,
        ...m.disks.filter((d) => d.percent >= 90).map((d) => `диск ${d.mount} ${Math.round(d.percent)}%`),
      ].filter(Boolean);
      if (hot.length) list.push({ key: "server", sev: "critical", title: "Сервер Fleet Manager перегружен", detail: hot.join(" · ") });
    }
    for (const a of activeAlerts) {
      const t = ALERT_TYPE[a.alert_type] ?? { label: a.alert_type, sev: "warning" as Sev };
      list.push({
        key: a.id,
        sev: t.sev,
        title: a.hostname ?? a.host_id.slice(0, 8),
        detail: `${t.label} · ${a.message}`,
        at: a.created_at,
        isNew: !acked.has(a.id),
      });
    }
    if (s) {
      if (s.disks_critical) list.push({ key: "disk", sev: "serious", weight: s.disks_critical, title: `Диск заполнен на ${pcCount(s.disks_critical)}`, detail: "свободного места почти не осталось" });
      if (s.kms_unreachable) list.push({ key: "kms", sev: "serious", weight: s.kms_unreachable, title: `KMS недоступен с ${pcCount(s.kms_unreachable)}`, detail: "активация Windows и Office не продлится" });
      if (s.tasks_failed_24h) list.push({ key: "tasks", sev: "warning", weight: s.tasks_failed_24h, title: `Задач с ошибкой за сутки: ${s.tasks_failed_24h}`, detail: "подробности — в разделе «Задачи»" });
      if (s.win_not_activated) list.push({ key: "win", sev: "warning", weight: s.win_not_activated, title: `Windows без активации: ${pcCount(s.win_not_activated)}`, detail: `${pct(s.win_not_activated, s.total)}% парка` });
      if (s.office_not_activated) list.push({ key: "office", sev: "warning", weight: s.office_not_activated, title: `Office без активации: ${pcCount(s.office_not_activated)}`, detail: `${pct(s.office_not_activated, s.total)}% парка` });
      if (s.agent_outdated) list.push({ key: "agent", sev: "info", weight: s.agent_outdated, title: `Устаревший агент: ${pcCount(s.agent_outdated)}`, detail: `актуальная версия ${s.agent_available_version ?? "—"}` });
      if (s.stale_7d) list.push({ key: "stale7", sev: "info", weight: s.stale_7d, title: `Не на связи больше 7 дней: ${pcCount(s.stale_7d)}`, detail: "ПК давно не отвечал" });
    }
    // Серьёзность → новые алерты → масштаб (сколько ПК) → свежесть
    return list.sort(
      (x, y) =>
        SEV_RANK[x.sev] - SEV_RANK[y.sev] ||
        Number(!!y.isNew) - Number(!!x.isNew) ||
        (y.weight ?? 0) - (x.weight ?? 0) ||
        (y.at ?? "").localeCompare(x.at ?? ""),
    );
  }, [s, m, activeAlerts, acked, stale]);

  const sevCounts = useMemo(() => {
    const c: Record<Sev, number> = { critical: 0, serious: 0, warning: 0, info: 0 };
    problems.forEach((p) => (c[p.sev] += 1));
    return c;
  }, [problems]);

  // Общий статус — главная мысль экрана, читается с другого конца комнаты
  const worst = problems.find((p) => p.sev !== "info");
  const overall = worst
    ? { sev: worst.sev, title: worst.sev === "critical" ? "Авария" : worst.sev === "serious" ? "Есть проблемы" : "Требует внимания", reason: worst.title }
    : { sev: "good" as const, title: "Всё в норме", reason: "проблем не обнаружено" };
  const OverallIcon = overall.sev === "good" ? CheckCircle2 : SEV[overall.sev].icon;
  const overallClass =
    overall.sev === "good"
      ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
      : overall.sev === "critical"
        ? "bg-rose-600 text-white"
        : SEV[overall.sev].chip;

  const [problemsRef, problemsCap] = useRowCapacity<HTMLDivElement>(PROBLEM_ROW_PX);
  const [devRef, devCap] = useRowCapacity<HTMLDivElement>(DEVIATION_ROW_PX);
  const problemsFit = fit(problems, problemsCap);
  const devFit = fit(deviations, devCap);

  const availability = s ? pct(s.online, s.total) : 0;
  const timelineData = (timeline.data ?? []).map((p) => p.online);
  const tasks = recentTasks.data ?? [];

  return (
    // Настенный дисплей: вся высота под шапкой приложения (3.5rem), без скролла.
    // 100vh (а не dvh): у ТВ нет динамических панелей, а старые webkit ТВ знают только vh.
    <div className="flex h-[calc(100vh-3.5rem)] flex-col gap-2.5 overflow-hidden p-3">
      {/* Шапка: общий статус + время */}
      <header className="flex shrink-0 items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <MonitorDot className="h-6 w-6 shrink-0 text-blue-600 dark:text-blue-400" />
          <h1 className="hidden truncate text-xl font-semibold tracking-tight text-foreground md:block">Мониторинг инфраструктуры</h1>
          <span className={`inline-flex min-w-0 items-center gap-2 rounded-full px-3 py-1 text-sm font-semibold ${overallClass} ${overall.sev === "critical" ? "animate-pulse" : ""}`}>
            <OverallIcon className="h-4 w-4 shrink-0" />
            <span className="shrink-0">{overall.title}</span>
            <span className="truncate font-normal opacity-90">· {overall.reason}</span>
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-4">
          <UpdatedAgo at={summary.dataUpdatedAt} />
          <Clock />
          <button
            onClick={() => {
              setSoundOn((v) => !v);
              kick();
            }}
            className={`inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm font-medium transition-colors ${
              soundOn ? "bg-blue-500/10 text-blue-600 dark:text-blue-400" : "bg-muted text-muted-foreground"
            }`}
            title="Звуковое оповещение о новых алертах"
          >
            {soundOn ? <Bell className="h-4 w-4" /> : <BellOff className="h-4 w-4" />}
            {soundOn ? "Звук" : "Без звука"}
          </button>
        </div>
      </header>

      {/* Ключевые показатели парка */}
      <div className="grid shrink-0 grid-cols-4 gap-2.5 xl:grid-cols-8">
        <Kpi icon={<Wifi className="h-4 w-4" />} label="В сети" value={s?.online ?? "—"} suffix={s ? `/ ${s.total}` : undefined}
          sub={s ? `доступность ${availability}%` : "загрузка…"} tone="good" meter={availability} />
        <Kpi icon={<WifiOff className="h-4 w-4" />} label="Не в сети" value={s?.offline ?? "—"}
          sub={s?.stale_7d ? `из них >7 дней: ${s.stale_7d}` : "выключены или недоступны"} tone="neutral" />
        <Kpi icon={<Bell className="h-4 w-4" />} label="Алерты за 24 ч" value={activeAlerts.length}
          sub={unacked.length ? `${unacked.length} новых` : activeAlerts.length ? "все приняты" : "нет"}
          tone={unacked.length ? "serious" : activeAlerts.length ? "warning" : "good"} />
        <Kpi icon={<KeyRound className="h-4 w-4" />} label="Windows без активации" value={s?.win_not_activated ?? "—"}
          sub={s ? `${pct(s.win_not_activated, s.total)}% парка` : ""} tone={s?.win_not_activated ? "warning" : "good"} />
        <Kpi icon={<KeyRound className="h-4 w-4" />} label="Office без активации" value={s?.office_not_activated ?? "—"}
          sub={s ? `${pct(s.office_not_activated, s.total)}% парка` : ""} tone={s?.office_not_activated ? "warning" : "good"} />
        <Kpi icon={<ShieldAlert className="h-4 w-4" />} label="KMS недоступен" value={s?.kms_unreachable ?? "—"}
          sub="активация не продлится" tone={s?.kms_unreachable ? "serious" : "good"} />
        <Kpi icon={<HardDrive className="h-4 w-4" />} label="Диск заполнен" value={s?.disks_critical ?? "—"}
          sub="почти нет места" tone={s?.disks_critical ? "serious" : "good"} />
        <Kpi icon={<ArrowUpCircle className="h-4 w-4" />} label="Агент устарел" value={s?.agent_outdated ?? "—"}
          sub={s?.agent_available_version ? `актуальная ${s.agent_available_version}` : ""} tone={s?.agent_outdated ? "info" : "good"} />
      </div>

      {/* Центр: корпуса и отклонения + проблемы и задачи */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-2.5 lg:grid-cols-12">
        <div className="flex min-h-0 flex-col gap-2.5 lg:col-span-7">
          {/* Корпуса */}
          <div className="grid shrink-0 grid-cols-2 gap-2.5 xl:grid-cols-4">
            {!s && <div className="surface-card col-span-full p-4 text-center text-sm text-muted-foreground">{summary.isError ? "Нет данных" : "Загрузка…"}</div>}
            {(s?.buildings ?? []).map((b) => <BuildingCard key={b.id} b={b} deviating={deviatingByBuilding.get(b.id) ?? 0} />)}
          </div>

          {/* Аудитории с отклонениями: только исключения, отсортированы по остроте */}
          <section className="surface-card flex min-h-0 flex-1 flex-col p-3">
            <div className="mb-2 flex shrink-0 flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
              <div className="flex items-baseline gap-2">
                <h2 className="text-sm font-semibold text-foreground">Аудитории с отклонениями</h2>
                {s && <span className="text-xs tabular-nums text-muted-foreground">{deviations.length} из {s.buildings.reduce((n, b) => n + b.floors.reduce((k, f) => k + f.rooms.length, 0), 0)}</span>}
              </div>
              <span className="text-[11px] text-muted-foreground">часть ПК выключена при работающих остальных · алерты · заполненный диск</span>
            </div>
            <div className="grid shrink-0 grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1.4fr)_4.5rem_3.5rem_3rem] gap-3 border-b border-border px-2 pb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              <span>Аудитория</span>
              <span>Где</span>
              <span>В сети</span>
              <span className="text-right">Не в сети</span>
              <span className="text-right">Алерты</span>
              <span className="text-right">Диск</span>
            </div>
            <div ref={devRef} className="min-h-0 flex-1 overflow-hidden pt-0.5">
              {s && deviations.length === 0 && (
                <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
                  <CheckCircle2 className="h-10 w-10 text-emerald-500" />
                  <p className="text-base font-semibold text-foreground">Отклонений нет</p>
                  <p className="text-sm text-muted-foreground">Во всех работающих аудиториях полный состав ПК</p>
                </div>
              )}
              {devFit.shown.map((d) => {
                const share = pct(d.online, d.total);
                return (
                  <div
                    key={d.id}
                    style={{ height: DEVIATION_ROW_PX }}
                    className={`grid grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1.4fr)_4.5rem_3.5rem_3rem] items-center gap-3 rounded-md px-2 text-sm ${
                      d.alerts || d.disk ? "bg-rose-500/5" : "odd:bg-muted/40"
                    }`}
                  >
                    <span className="truncate font-semibold text-foreground">{d.name}</span>
                    <span className="truncate text-xs text-muted-foreground">{d.where}</span>
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="w-14 shrink-0 tabular-nums text-foreground">{d.online} / {d.total}</span>
                      <span className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-muted">
                        <span className="block h-full rounded-full bg-blue-600" style={{ width: `${share}%` }} />
                      </span>
                    </span>
                    <span className={`text-right tabular-nums ${d.missing ? "font-semibold text-amber-700 dark:text-amber-300" : "text-subtle"}`}>
                      {d.missing ? pcCount(d.missing) : "—"}
                    </span>
                    <span className="flex justify-end">
                      {d.alerts ? (
                        <span className="inline-flex items-center gap-1 rounded-md bg-rose-600 px-1.5 py-0.5 text-xs font-bold tabular-nums text-white">
                          <Bell className="h-3 w-3" />{d.alerts}
                        </span>
                      ) : (
                        <span className="text-subtle">—</span>
                      )}
                    </span>
                    <span className="flex justify-end">
                      {d.disk ? <HardDrive className="h-4 w-4 text-orange-600 dark:text-orange-400" aria-label="заполнен диск" /> : <span className="text-subtle">—</span>}
                    </span>
                  </div>
                );
              })}
              {devFit.hidden > 0 && (
                <div style={{ height: DEVIATION_ROW_PX }} className="flex items-center px-2 text-xs text-muted-foreground">
                  и ещё {devFit.hidden} {devFit.hidden === 1 ? "аудитория" : devFit.hidden < 5 ? "аудитории" : "аудиторий"}
                </div>
              )}
            </div>
          </section>
        </div>

        <div className="flex min-h-0 flex-col gap-2.5 lg:col-span-5">
          {/* Проблемы — по серьёзности; новые алерты подсвечивают блок и пищат */}
          <section
            className={`flex min-h-0 flex-1 flex-col rounded-xl p-3 ${
              unacked.length ? "border-2 border-rose-500/70 bg-rose-500/5 shadow-panel-lg" : "surface-card"
            }`}
          >
            <div className="mb-1.5 flex shrink-0 flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <AlertTriangle className={`h-4 w-4 ${unacked.length ? "animate-pulse text-rose-600 dark:text-rose-400" : "text-blue-600 dark:text-blue-400"}`} />
                <h2 className="text-sm font-semibold text-foreground">Проблемы</h2>
                {(["critical", "serious", "warning", "info"] as Sev[]).map((k) =>
                  sevCounts[k] ? (
                    <span key={k} className={`rounded-md px-1.5 py-0.5 text-[11px] font-semibold tabular-nums ${SEV[k].chip}`} title={SEV[k].label}>
                      {sevCounts[k]}
                    </span>
                  ) : null,
                )}
              </div>
              {unacked.length > 0 && (
                <button
                  onClick={() => setAcked(new Set(activeAlerts.map((a) => a.id)))}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-rose-600 px-2.5 py-1 text-xs font-semibold text-white transition-colors hover:bg-rose-700"
                  title="Заглушить звук по текущим алертам — новый алерт снова включит сигнал"
                >
                  <BellOff className="h-3.5 w-3.5" /> Принять ({unacked.length})
                </button>
              )}
            </div>
            <div ref={problemsRef} className="min-h-0 flex-1 overflow-hidden">
              {problems.length === 0 ? (
                <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
                  <CheckCircle2 className="h-12 w-12 text-emerald-500" />
                  <p className="text-lg font-semibold text-foreground">Проблем нет</p>
                  <p className="text-sm text-muted-foreground">Всё работает штатно</p>
                </div>
              ) : (
                <>
                  {problemsFit.shown.map((p) => {
                    const Icon = SEV[p.sev].icon;
                    return (
                      <div key={p.key} style={{ height: PROBLEM_ROW_PX }} className={`flex items-center gap-2.5 rounded-lg px-2 ${p.isNew ? "bg-rose-500/10" : ""}`}>
                        <Icon className={`h-4 w-4 shrink-0 ${SEV[p.sev].text}`} aria-label={SEV[p.sev].label} />
                        <div className="min-w-0 flex-1 leading-tight">
                          <div className="flex items-center gap-1.5">
                            <span className="truncate text-sm font-semibold text-foreground">{p.title}</span>
                            {p.isNew && <span className="shrink-0 rounded bg-rose-600 px-1 py-px text-[10px] font-bold uppercase text-white">новый</span>}
                          </div>
                          <div className="truncate text-xs text-muted-foreground" title={p.detail}>{p.detail}</div>
                        </div>
                        {p.at && <span className="shrink-0 text-xs tabular-nums text-subtle">{ago(p.at, now)}</span>}
                      </div>
                    );
                  })}
                  {problemsFit.hidden > 0 && (
                    <div style={{ height: PROBLEM_ROW_PX }} className="flex items-center px-2 text-xs text-muted-foreground">
                      и ещё {problemsFit.hidden}
                    </div>
                  )}
                </>
              )}
            </div>
          </section>

          {/* Задачи */}
          <section className="surface-card flex shrink-0 flex-col p-3">
            <div className="mb-1.5 flex flex-wrap items-center gap-2">
              <Activity className="h-4 w-4 text-blue-600 dark:text-blue-400" />
              <h2 className="text-sm font-semibold text-foreground">Задачи</h2>
              {s && s.tasks_running > 0 && (
                <span className="rounded-md bg-blue-500/15 px-1.5 py-0.5 text-[11px] font-semibold tabular-nums text-blue-700 dark:text-blue-300">
                  идёт {s.tasks_running}
                </span>
              )}
              {s && s.tasks_failed_24h > 0 && (
                <span className="rounded-md bg-rose-500/15 px-1.5 py-0.5 text-[11px] font-semibold tabular-nums text-rose-700 dark:text-rose-300">
                  ошибок за сутки {s.tasks_failed_24h}
                </span>
              )}
            </div>
            <div className="space-y-0.5">
              {tasks.length === 0 && <p className="py-2 text-center text-xs text-muted-foreground">Задач пока нет</p>}
              {tasks.slice(0, TASK_ROWS).map((t, i) => {
                const st = TASK_STATUS[t.status] ?? { label: t.status, dot: "bg-slate-400", text: "text-muted-foreground" };
                return (
                  <div key={t.id} className={`flex h-7 items-center gap-2 rounded-md px-1.5 text-sm odd:bg-muted/40 ${i >= 2 ? SHORT_HIDE : ""}`}>
                    <span className={`h-2 w-2 shrink-0 rounded-full ${st.dot} ${st.pulse ? "animate-pulse" : ""}`} />
                    <span className="min-w-0 flex-1 truncate text-foreground">{taskTitle(t)}</span>
                    <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{pcCount(t.host_ids.length)}</span>
                    <span className={`w-14 shrink-0 text-right text-xs font-medium ${st.text}`}>{st.label}</span>
                    <span className="w-11 shrink-0 text-right text-xs tabular-nums text-subtle">{ago(t.created_at, now)}</span>
                  </div>
                );
              })}
            </div>
          </section>
        </div>
      </div>

      {/* Сервер Fleet Manager */}
      <section className="shrink-0">
        <div className="mb-1.5 flex items-center gap-2 text-xs text-muted-foreground">
          {m ? <Server className="h-3.5 w-3.5 text-blue-600 dark:text-blue-400" /> : <ServerOff className="h-3.5 w-3.5 text-rose-500" />}
          <span className="font-medium text-foreground">Сервер Fleet Manager</span>
          {m && <span className="truncate tabular-nums">· аптайм {formatUptime(m.uptime_seconds)} · нагрузка {m.load_avg.map((x) => x.toFixed(1)).join(" / ")}</span>}
          {!m && <span>{metrics.isError ? "метрики недоступны" : "загрузка…"}</span>}
        </div>
        <div className="grid grid-cols-3 gap-2.5 xl:grid-cols-6">
          {m && (
            <>
              <MetricCell icon={<Cpu className="h-3.5 w-3.5" />} label="CPU" value={`${Math.round(m.cpu_percent)}%`} pctValue={m.cpu_percent}
                spark={cpuHist} sparkClass={loadTone(m.cpu_percent).text} detail={`${m.cpu_count} ядер · за 5 мин`} />
              <MetricCell icon={<MemoryStick className="h-3.5 w-3.5" />} label="Память" value={`${Math.round(m.mem_percent)}%`} pctValue={m.mem_percent}
                detail={`${m.mem_used_gb} из ${m.mem_total_gb} ГБ${m.swap_percent > 0 ? ` · swap ${Math.round(m.swap_percent)}%` : ""}`} />
              <MetricCell icon={<Network className="h-3.5 w-3.5" />} label="Сеть" value={`${(m.net_recv_mbps + m.net_sent_mbps).toFixed(1)} Мбит/с`}
                spark={netHist} sparkClass="text-blue-500" detail={`↓ ${m.net_recv_mbps.toFixed(1)} · ↑ ${m.net_sent_mbps.toFixed(1)} Мбит/с`} />
              {m.disks.slice(0, 2).map((d) => (
                <MetricCell key={d.mount} icon={<HardDrive className="h-3.5 w-3.5" />} label={d.mount === "/" ? "Диск системы" : `Диск ${d.mount}`}
                  value={`${Math.round(d.percent)}%`} pctValue={d.percent}
                  detail={`занято ${d.used_gb} из ${d.total_gb} ГБ · свободно ${(d.total_gb - d.used_gb).toFixed(0)} ГБ`} />
              ))}
              <MetricCell icon={<Wifi className="h-3.5 w-3.5" />} label="ПК в сети за 24 ч" value={timelineData.length ? `${timelineData[timelineData.length - 1]}` : "—"}
                spark={timelineData} sparkClass="text-blue-500"
                detail={timelineData.length ? `максимум ${Math.max(...timelineData)} · минимум ${Math.min(...timelineData)}` : "нет данных"} />
            </>
          )}
        </div>
      </section>
    </div>
  );
}
