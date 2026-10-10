import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CalendarClock, GitBranch, Play } from "lucide-react";
import { apiClient } from "../api/client";
import { keys, useFleet, usePlaybookFiles, useRepos } from "../api/queries";
import HostPicker from "./HostPicker";
import PlaybookSelect, { rememberPlaybook } from "./PlaybookSelect";
import ExtraVarsEditor, { VarPair, varsToObject } from "./ExtraVarsEditor";
import Button from "./ui/Button";
import { ErrorText } from "./ui/States";
import { useToast } from "./ui/Toast";
import { useOpenTask } from "./TaskPanel";
import { compactSelection } from "../lib/groupTree";
import { CRON_PRESETS, describeCron } from "../lib/cron";
import { apiError, pcCount } from "../lib/format";

interface Props {
  initialHostIds?: string[];
  /** Вызывается после запуска или создания расписания (закрыть модалку) */
  onDone?: () => void;
  pickerHeight?: number;
  initialMode?: "now" | "schedule";
}

/** Запуск плейбука: что (каталог) → где (дерево хостов) → параметры → сейчас или по расписанию. */
export default function PlaybookRunForm({ initialHostIds = [], onDone, pickerHeight = 340, initialMode = "now" }: Props) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const openTask = useOpenTask();
  const { tree, hostById } = useFleet();
  const repos = useRepos();
  const [repoId, setRepoId] = useState("");
  const files = usePlaybookFiles(repoId || null);
  const [playbook, setPlaybook] = useState("");
  const [selection, setSelection] = useState<Set<string>>(() => new Set(initialHostIds));
  const [vars, setVars] = useState<VarPair[]>([]);
  const [mode, setMode] = useState<"now" | "schedule">(initialMode);
  const [cron, setCron] = useState(CRON_PRESETS[0].value);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!repoId && repos.data?.length) setRepoId(repos.data[0].id);
  }, [repos.data, repoId]);

  const offline = useMemo(() => [...selection].filter((id) => hostById.get(id)?.status !== "online").length, [selection, hostById]);
  const repo = repos.data?.find((r) => r.id === repoId);

  async function syncRepo() {
    if (!repoId) return;
    setBusy(true);
    try {
      await apiClient.post(`/playbooks/repos/${repoId}/sync`);
      await queryClient.invalidateQueries({ queryKey: keys.files(repoId) });
      toast({ tone: "success", message: "Каталог плейбуков обновлён из git" });
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось обновить репозиторий") });
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (!repoId || !playbook || selection.size === 0) return;
    const { groupIds, hostIds } = compactSelection(tree, selection);
    setError(null);
    if (mode === "now" && selection.size > 30 && !window.confirm(`Запустить плейбук на ${pcCount(selection.size)}?`)) return;
    setBusy(true);
    try {
      if (mode === "now") {
        const { data } = await apiClient.post<{ task_run_id: string }>("/playbooks/run", {
          repo_id: repoId,
          playbook_name: playbook,
          host_ids: hostIds,
          host_group_ids: groupIds,
          extra_vars: varsToObject(vars),
        });
        rememberPlaybook(playbook);
        queryClient.invalidateQueries({ queryKey: ["tasks"] });
        onDone?.();
        openTask(data.task_run_id);
      } else {
        await apiClient.post("/playbooks/schedules", {
          repo_id: repoId,
          playbook_name: playbook,
          host_ids: hostIds,
          host_group_ids: groupIds,
          extra_vars: varsToObject(vars),
          cron_expression: cron,
          enabled: true,
        });
        rememberPlaybook(playbook);
        queryClient.invalidateQueries({ queryKey: keys.schedules });
        toast({ tone: "success", message: `Расписание создано: ${describeCron(cron) ?? cron}` });
        onDone?.();
      }
    } catch (err) {
      setError(apiError(err, mode === "now" ? "Не удалось запустить плейбук" : "Не удалось создать расписание"));
    } finally {
      setBusy(false);
    }
  }

  if (repos.data && repos.data.length === 0) {
    return <p className="text-sm text-muted-foreground">Нет подключённых репозиториев — подключите его на вкладке «Репозитории».</p>;
  }

  return (
    <div className="space-y-5">
      <section className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <label className="field-label mb-0">1. Плейбук</label>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            {(repos.data?.length ?? 0) > 1 ? (
              <select value={repoId} onChange={(e) => { setRepoId(e.target.value); setPlaybook(""); }} className="input-base w-auto py-1 text-xs">
                {repos.data!.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
              </select>
            ) : (
              repo && (
                <span className="inline-flex items-center gap-1">
                  <GitBranch className="h-3 w-3" />
                  {repo.name} · <span className="font-mono">{repo.branch}</span>
                </span>
              )
            )}
            <button type="button" className="text-blue-600 hover:underline disabled:opacity-50 dark:text-blue-400" onClick={syncRepo} disabled={busy || !repoId}>
              обновить из git
            </button>
          </div>
        </div>
        <PlaybookSelect files={files.data ?? []} value={playbook} onChange={setPlaybook} loading={repos.isLoading || !repoId || files.isLoading} />
      </section>

      <section className="space-y-2">
        <label className="field-label mb-0">2. Хосты</label>
        <HostPicker value={selection} onChange={setSelection} height={pickerHeight} />
        {offline > 0 && (
          <p className="flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400">
            <AlertTriangle className="h-3.5 w-3.5" />
            {offline} из {pcCount(selection.size)} сейчас не online — на них запуск, скорее всего, завершится ошибкой
          </p>
        )}
      </section>

      <details className="group rounded-lg border border-border px-3 py-2" open={vars.length > 0}>
        <summary className="cursor-pointer text-sm text-muted-foreground">
          3. Переменные (extra vars){vars.length > 0 && ` · ${vars.filter((v) => v.key).length}`}
        </summary>
        <div className="mt-3">
          <ExtraVarsEditor value={vars} onChange={setVars} />
        </div>
      </details>

      <section className="space-y-3 border-t border-border pt-4">
        <div className="inline-flex rounded-lg border border-border bg-muted/40 p-0.5" role="radiogroup">
          {(["now", "schedule"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={mode === m}
              onClick={() => setMode(m)}
              className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${mode === m ? "bg-surface text-foreground shadow-panel" : "text-muted-foreground hover:text-foreground"}`}
            >
              {m === "now" ? "Запустить сейчас" : "По расписанию"}
            </button>
          ))}
        </div>

        {mode === "schedule" && (
          <div className="flex flex-wrap items-center gap-2">
            {CRON_PRESETS.map((p) => (
              <button key={p.value} type="button" onClick={() => setCron(p.value)} className={cron === p.value ? "chip-on" : "chip-off"}>
                {p.label}
              </button>
            ))}
            <input value={cron} onChange={(e) => setCron(e.target.value)} className="input-base w-36 py-1 font-mono text-xs" aria-label="Cron-выражение" />
            <span className="text-xs text-muted-foreground">{describeCron(cron) ?? "своё cron-выражение: минута час день месяц день_недели"}</span>
            <p className="w-full text-xs text-subtle">Выбранные группы раскрываются при каждом запуске: новые ПК в аудитории попадут в расписание сами.</p>
          </div>
        )}

        <ErrorText>{error}</ErrorText>
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={submit} loading={busy} disabled={!playbook || selection.size === 0}>
            {mode === "now" ? <Play className="h-4 w-4" /> : <CalendarClock className="h-4 w-4" />}
            {mode === "now" ? `Запустить на ${pcCount(selection.size)}` : "Создать расписание"}
          </Button>
          {!playbook && <span className="text-xs text-subtle">Выберите плейбук</span>}
          {playbook && selection.size === 0 && <span className="text-xs text-subtle">Выберите хосты</span>}
        </div>
      </section>
    </div>
  );
}
