import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Bell, BellOff, CheckCircle2, MonitorDot, ServerCrash, Wifi } from "lucide-react";
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

function Tile({ icon, label, value, tone }: { icon: React.ReactNode; label: string; value: number | string; tone: "ok" | "warn" | "bad" | "neutral" }) {
  const toneClass = {
    ok: "text-emerald-600 dark:text-emerald-400",
    warn: "text-amber-600 dark:text-amber-400",
    bad: "text-rose-600 dark:text-rose-400",
    neutral: "text-foreground",
  }[tone];
  return (
    <div className="surface-card flex items-center gap-4 p-5">
      <div className={`flex h-12 w-12 items-center justify-center rounded-xl bg-muted ${toneClass}`}>{icon}</div>
      <div>
        <div className={`text-3xl font-bold tabular-nums ${toneClass}`}>{value}</div>
        <div className="text-sm text-muted-foreground">{label}</div>
      </div>
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

  // пересчитываем «свежесть» алертов каждые 30с
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 30000);
    return () => window.clearInterval(id);
  }, []);

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

  const kick = useBeeper(hasAlerts, soundOn);

  const s = summary.data;

  return (
    <div className="animate-fade-in space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <MonitorDot className="h-6 w-6 text-blue-600 dark:text-blue-400" />
          <h1 className="text-2xl font-semibold tracking-tight">Мониторинг инфраструктуры</h1>
        </div>
        <button
          onClick={() => {
            setSoundOn((v) => !v);
            kick();
          }}
          className={`inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm font-medium transition-colors ${
            soundOn ? "bg-blue-500/10 text-blue-600 dark:text-blue-400" : "bg-muted text-muted-foreground"
          }`}
          title="Звуковое оповещение об алертах"
        >
          {soundOn ? <Bell className="h-4 w-4" /> : <BellOff className="h-4 w-4" />}
          Звук {soundOn ? "вкл" : "выкл"}
        </button>
      </div>

      {/* Ключевые метрики инфраструктуры */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Tile icon={<Wifi className="h-6 w-6" />} label="Хостов онлайн" value={s?.online ?? "—"} tone="ok" />
        <Tile icon={<ServerCrash className="h-6 w-6" />} label="Хостов офлайн" value={s?.offline ?? "—"} tone={s && s.offline > 0 ? "bad" : "neutral"} />
        <Tile icon={<MonitorDot className="h-6 w-6" />} label="Всего хостов" value={s?.total ?? "—"} tone="neutral" />
        <Tile icon={<AlertTriangle className="h-6 w-6" />} label="Активных алертов (24ч)" value={activeAlerts.length} tone={hasAlerts ? "bad" : "ok"} />
      </div>

      {/* Крупный блок алертов */}
      {hasAlerts ? (
        <div className="rounded-2xl border-2 border-rose-500/70 bg-rose-500/5 p-5 shadow-panel-lg">
          <div className="mb-4 flex items-center gap-3">
            <AlertTriangle className="h-8 w-8 animate-pulse text-rose-600 dark:text-rose-400" />
            <h2 className="text-2xl font-bold text-rose-600 dark:text-rose-400">
              {activeAlerts.length} {activeAlerts.length === 1 ? "активный алерт" : "активных алертов"}
            </h2>
          </div>
          <div className="space-y-3">
            {activeAlerts.map((a) => (
              <div key={a.id} className="rounded-xl border border-rose-500/40 bg-background/60 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-lg font-bold text-rose-600 dark:text-rose-400">
                    {hostName.get(a.host_id) ?? a.host_id.slice(0, 8)}
                  </span>
                  <span className="rounded-md bg-rose-500/15 px-2 py-0.5 text-sm font-semibold text-rose-600 dark:text-rose-400">
                    {a.alert_type}
                  </span>
                  <span className="text-sm text-muted-foreground">{new Date(a.created_at).toLocaleString()}</span>
                </div>
                <p className="mt-1 text-base text-foreground">{a.message}</p>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="surface-card flex flex-col items-center justify-center gap-3 p-10 text-center">
          <CheckCircle2 className="h-14 w-14 text-emerald-500" />
          <p className="text-2xl font-semibold text-foreground">Всё спокойно</p>
          <p className="text-muted-foreground">Активных алертов за последние 24 часа нет.</p>
        </div>
      )}

      {(alerts.isError || summary.isError) && (
        <p className="text-sm text-rose-600 dark:text-rose-400">Не удалось загрузить данные мониторинга — проверяется автоматически каждые 15 секунд.</p>
      )}
    </div>
  );
}
