import { useEffect, useState } from "react";
import { RefreshCw, Server } from "lucide-react";
import { apiClient } from "../api/client";
import { apiError, formatSize, plural, relativeTime } from "../lib/format";
import Button from "./ui/Button";

export interface Distribution {
  enabled: boolean;
  url: string | null;
  running: boolean;
  healthy: boolean | null;
  last_success: string | null;
  last_attempt: string | null;
  error: string | null;
  files: number | null;
  bytes: number | null;
  pending: number | null;
}

type Tone = "ok" | "busy" | "bad" | "off";

const DOT: Record<Tone, string> = {
  ok: "bg-emerald-500",
  busy: "bg-amber-500 animate-pulse",
  bad: "bg-rose-500",
  off: "bg-slate-400",
};

function summary(d: Distribution): { tone: Tone; title: string } {
  if (!d.enabled) return { tone: "off", title: "Точка раздачи не настроена — файлы копируются с сервера по SSH" };
  if (d.running) return { tone: "busy", title: "Идёт синхронизация" };
  if (d.healthy === false) return { tone: "bad", title: "Точка раздачи не отвечает — файлы копируются с сервера по SSH" };
  if (d.error) return { tone: "bad", title: "Последняя синхронизация не удалась" };
  if (!d.last_success) return { tone: "busy", title: "Ещё не синхронизирована" };
  return { tone: "ok", title: "Работает" };
}

/** Зеркало шары на сервере рядом с ПК: ПК качают установщики оттуда по HTTP, а не по SSH с бэкенда. */
export default function DistributionStatus({ canManage, onSynced }: { canManage: boolean; onSynced?: () => void }) {
  const [state, setState] = useState<Distribution | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  async function load() {
    try {
      const { data } = await apiClient.get<Distribution>("/installers/distribution");
      setState((prev) => {
        if (prev?.running && !data.running) onSynced?.();
        return data;
      });
    } catch (e) {
      setError(apiError(e, "Не удалось получить состояние точки раздачи"));
    }
  }

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    if (!state?.running) return;
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, [state?.running]);

  async function sync() {
    setStarting(true);
    setError(null);
    try {
      const { data } = await apiClient.post<Distribution>("/installers/distribution/sync");
      setState({ ...data, running: true });
    } catch (e) {
      setError(apiError(e, "Не удалось запустить синхронизацию"));
    } finally {
      setStarting(false);
    }
  }

  if (!state) return error ? <p className="text-sm text-rose-600 dark:text-rose-400">{error}</p> : null;
  const { tone, title } = summary(state);
  const host = state.url?.replace(/^https?:\/\//, "");

  return (
    <section aria-label="Точка раздачи" className="surface-panel flex flex-wrap items-start justify-between gap-3">
      <div className="flex min-w-0 items-start gap-3">
        <Server className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" aria-hidden="true" />
        <div className="min-w-0 space-y-1">
          <p className="flex flex-wrap items-center gap-x-2 text-sm font-medium text-foreground">
            <span>Точка раздачи{host && <span className="ml-1 font-mono font-normal text-muted-foreground">{host}</span>}</span>
            <span className="inline-flex items-center gap-1.5 font-normal text-muted-foreground">
              <span className={`h-2 w-2 rounded-full ${DOT[tone]}`} aria-hidden="true" />
              {title}
            </span>
          </p>
          {state.enabled && (
            <p className="text-sm text-muted-foreground">
              {state.last_success ? `Синхронизирована ${relativeTime(state.last_success)}` : "Синхронизаций ещё не было"}
              {state.files != null && ` · ${plural(state.files, "файл", "файла", "файлов")}, ${formatSize(state.bytes ?? 0)}`}
              {!!state.pending && ` · ${plural(state.pending, "файл менялся", "файла менялись", "файлов менялись")} во время передачи — уйдут следующей синхронизацией`}
            </p>
          )}
          {state.enabled && (
            <p className="text-xs text-subtle">
              ПК скачивают установщики оттуда по HTTP; файл, которого там ещё нет, копируется с сервера по SSH. Синхронизация — после загрузки файла и каждые 15 минут.
            </p>
          )}
          {state.error && !state.running && <p className="text-sm text-rose-600 dark:text-rose-400">{state.error}</p>}
          {error && <p className="text-sm text-rose-600 dark:text-rose-400">{error}</p>}
        </div>
      </div>
      {canManage && state.enabled && (
        <Button variant="secondary" onClick={sync} loading={starting} disabled={state.running}>
          <RefreshCw className={`h-4 w-4 ${state.running ? "animate-spin" : ""}`} aria-hidden="true" />
          {state.running ? "Синхронизируется…" : "Синхронизировать"}
        </Button>
      )}
    </section>
  );
}
