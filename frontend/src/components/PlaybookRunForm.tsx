import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { AlertTriangle, CalendarClock, FileCode2, Play, Plus } from "lucide-react";
import { apiClient } from "../api/client";
import { keys, useFleet, usePlaybookCatalog } from "../api/queries";
import HostPicker from "./HostPicker";
import PlaybookSelect, { catalogKey, rememberPlaybook } from "./PlaybookSelect";
import ExtraVarsEditor, { VarPair, varsToObject } from "./ExtraVarsEditor";
import Button from "./ui/Button";
import Switch from "./ui/Switch";
import { ErrorText } from "./ui/States";
import { useToast } from "./ui/Toast";
import { useOpenTask } from "./TaskPanel";
import { compactSelection } from "../lib/groupTree";
import { DEFAULT_CRON, describeCron, isValidCron } from "../lib/cron";
import CronEditor from "./CronEditor";
import { apiError, pcCount, waitingNotice } from "../lib/format";

interface Props {
  initialHostIds?: string[];
  /** Вызывается после запуска или создания расписания (закрыть модалку) */
  onDone?: () => void;
  pickerHeight?: number;
  initialMode?: "now" | "schedule";
  /** Сразу выбранный плейбук — например, после сохранения в редакторе */
  initialRepoId?: string;
  initialPlaybook?: string;
}

/** Запуск плейбука: что (каталог) → где (дерево хостов) → параметры → сейчас или по расписанию. */
export default function PlaybookRunForm({ initialHostIds = [], onDone, pickerHeight = 340, initialMode = "now", initialRepoId, initialPlaybook }: Props) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const openTask = useOpenTask();
  const { tree, hostById } = useFleet();
  const catalog = usePlaybookCatalog();
  const repos = catalog.repos;
  // Ключ каталога repo_id::path: плейбуки всех источников в одном списке
  const [selectedKey, setSelectedKey] = useState(initialRepoId && initialPlaybook ? catalogKey(initialRepoId, initialPlaybook) : "");
  const selectedFile = catalog.files.find((f) => f.key === selectedKey);
  const repoId = selectedFile?.repo_id ?? "";
  const playbook = selectedFile?.path ?? "";
  const [selection, setSelection] = useState<Set<string>>(() => new Set(initialHostIds));
  const [vars, setVars] = useState<VarPair[]>([]);
  const [mode, setMode] = useState<"now" | "schedule">(initialMode);
  const [cron, setCron] = useState(DEFAULT_CRON);
  // Выключенным ПК — отдельные задачи, которые запустятся, когда ПК появится в сети
  const [deferOffline, setDeferOffline] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const offline = useMemo(() => [...selection].filter((id) => hostById.get(id)?.status !== "online").length, [selection, hostById]);
  const gitRepos = (repos.data ?? []).filter((r) => r.kind !== "local");

  async function syncRepo() {
    if (gitRepos.length === 0) return;
    setBusy(true);
    try {
      for (const r of gitRepos) {
        await apiClient.post(`/playbooks/repos/${r.id}/sync`);
        await queryClient.invalidateQueries({ queryKey: keys.files(r.id) });
      }
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
        const { data } = await apiClient.post<{ task_run_id: string; waiting_task_ids: string[] }>("/playbooks/run", {
          repo_id: repoId,
          playbook_name: playbook,
          host_ids: hostIds,
          host_group_ids: groupIds,
          extra_vars: varsToObject(vars),
          defer_offline: deferOffline,
        });
        rememberPlaybook(selectedKey);
        queryClient.invalidateQueries({ queryKey: ["tasks"] });
        onDone?.();
        const waiting = data.waiting_task_ids?.length ?? 0;
        if (waiting > 0) toast({ tone: "info", message: waitingNotice(waiting, !data.waiting_task_ids.includes(data.task_run_id)) });
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
        rememberPlaybook(selectedKey);
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


  return (
    <div className="space-y-5">
      <section className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <label className="field-label mb-0">1. Плейбук</label>
          {gitRepos.length > 0 && (
            <button type="button" className="text-xs text-blue-600 hover:underline disabled:opacity-50 dark:text-blue-400" onClick={syncRepo} disabled={busy}>
              обновить из git
            </button>
          )}
        </div>
        <div className="flex gap-2">
          <div className="min-w-0 flex-1">
            <PlaybookSelect files={catalog.files} value={selectedKey} onChange={setSelectedKey} loading={catalog.isLoading} />
          </div>
          {selectedFile && (
            <Link
              to={`/automation/editor?repo=${selectedFile.repo_id}&path=${encodeURIComponent(selectedFile.path)}`}
              className="btn-secondary px-2.5"
              title={selectedFile.local ? "Открыть в редакторе" : "Открыть текст плейбука (из git — только просмотр и копия в локальные)"}
              aria-label="Открыть плейбук в редакторе"
            >
              <FileCode2 className="h-4 w-4" />
            </Link>
          )}
          <Link to="/automation/editor" className="btn-secondary px-2.5" title="Новый плейбук" aria-label="Новый плейбук">
            <Plus className="h-4 w-4" />
          </Link>
        </div>
      </section>

      <section className="space-y-2">
        <label className="field-label mb-0">2. Хосты</label>
        <HostPicker value={selection} onChange={setSelection} height={pickerHeight} />
        {offline > 0 && mode === "now" && (
          <div className="flex items-start gap-2.5 text-xs">
            <Switch checked={deferOffline} onChange={setDeferOffline} label="Запустить на выключенных ПК, когда они появятся в сети" />
            <p className={deferOffline ? "text-muted-foreground" : "flex items-center gap-1.5 text-amber-600 dark:text-amber-400"}>
              {!deferOffline && <AlertTriangle className="h-3.5 w-3.5 shrink-0" />}
              {offline} из {pcCount(selection.size)} сейчас не в сети.{" "}
              {deferOffline
                ? "На них задача запустится, когда они появятся в сети (ждём до 7 дней)."
                : "На них запуск, скорее всего, завершится ошибкой."}
            </p>
          </div>
        )}
        {offline > 0 && mode === "schedule" && (
          <p className="flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400">
            <AlertTriangle className="h-3.5 w-3.5" />
            {offline} из {pcCount(selection.size)} сейчас не в сети — если при срабатывании расписания они будут выключены, запуск на них завершится ошибкой
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
          <div className="space-y-2">
            <CronEditor value={cron} onChange={setCron} />
            <p className="text-xs text-subtle">Выбранные группы раскрываются при каждом запуске: новые ПК в аудитории попадут в расписание сами.</p>
          </div>
        )}

        <ErrorText>{error}</ErrorText>
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={submit} loading={busy} disabled={!playbook || selection.size === 0 || (mode === "schedule" && !isValidCron(cron))}>
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
