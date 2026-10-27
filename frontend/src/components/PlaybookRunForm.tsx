import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { AlertTriangle, ArrowDown, ArrowUp, CalendarClock, FileCode2, ListPlus, Play, Plus, X } from "lucide-react";
import { apiClient } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { keys, useFleet, usePlaybookCatalog } from "../api/queries";
import HostPicker from "./HostPicker";
import { TagTargets, tagHostIds, useTagById } from "./HostTags";
import PlaybookSelect, { catalogKey, PlaybookDetails, playbookLabel, rememberPlaybook } from "./PlaybookSelect";
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

/** Запуск плейбука: что (каталог) → где (дерево хостов) → параметры → сейчас или по расписанию.
 *  Сейчас можно запустить несколько плейбуков: каждый — отдельная задача, по очереди. */
export default function PlaybookRunForm({ initialHostIds = [], onDone, pickerHeight = 340, initialMode = "now", initialRepoId, initialPlaybook }: Props) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const openTask = useOpenTask();
  const { user } = useAuth();
  const canEdit = user?.role === "admin"; // редактор плейбуков — только админ
  const { tree, hostById, hosts } = useFleet();
  const catalog = usePlaybookCatalog();
  const repos = catalog.repos;
  // Ключи каталога repo_id::path по порядку выполнения: плейбуки всех источников в одном списке
  const [selectedKeys, setSelectedKeys] = useState<string[]>([initialRepoId && initialPlaybook ? catalogKey(initialRepoId, initialPlaybook) : ""]);
  const selectedFiles = selectedKeys.map((key) => catalog.files.find((f) => f.key === key));
  const chosen = selectedFiles.filter((f): f is NonNullable<typeof f> => !!f);
  const repoId = chosen[0]?.repo_id ?? "";
  const playbook = chosen[0]?.path ?? "";
  const [mode, setMode] = useState<"now" | "schedule">(initialMode);
  // Один запуск — один источник: сервер берёт плейбуки из одного репозитория
  const mixedSources = new Set(chosen.map((f) => f.repo_id)).size > 1;
  const tooManyForSchedule = mode === "schedule" && chosen.length > 1;
  const setKeyAt = (index: number, key: string) => setSelectedKeys((prev) => prev.map((k, i) => (i === index ? key : k)));
  const removeAt = (index: number) => setSelectedKeys((prev) => (prev.length > 1 ? prev.filter((_, i) => i !== index) : [""]));
  const move = (index: number, delta: number) =>
    setSelectedKeys((prev) => {
      const next = [...prev];
      [next[index], next[index + delta]] = [next[index + delta], next[index]];
      return next;
    });
  const [selection, setSelection] = useState<Set<string>>(() => new Set(initialHostIds));
  // Теги раскрываются в ПК на сервере в момент запуска (у расписания — при каждом срабатывании)
  const [tagIds, setTagIds] = useState<Set<string>>(() => new Set());
  const tagged = useMemo(() => tagHostIds(hosts, tagIds), [hosts, tagIds]);
  const targets = useMemo(() => new Set([...selection, ...tagged]), [selection, tagged]);
  const tagById = useTagById();
  const hasTargets = selection.size > 0 || tagIds.size > 0;
  const [vars, setVars] = useState<VarPair[]>([]);
  const [cron, setCron] = useState(DEFAULT_CRON);
  // Выключенным ПК — общая ожидающая задача: запустится для каждого, когда он появится в сети
  const [deferOffline, setDeferOffline] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const offline = useMemo(() => [...targets].filter((id) => hostById.get(id)?.status !== "online").length, [targets, hostById]);
  const gitRepos = (repos.data ?? []).filter((r) => r.kind !== "local");
  // От чьего имени пойдёт плейбук (backend/services/run_as.py)
  const runAsHint =
    user?.auth_source === "ldap"
      ? `От вашего имени (${user.username}) там, где вы администратор ПК, на остальных — от учётки установки агента${mode === "schedule" ? "; расписание — от имени того, кто его последним изменил" : ""}`
      : "От учётки установки агента: вы вошли локальной учётной записью";

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
    if (!repoId || !playbook || !hasTargets || mixedSources || tooManyForSchedule) return;
    const { groupIds, hostIds } = compactSelection(tree, selection);
    setError(null);
    const what = chosen.length > 1 ? `${chosen.length} плейбука по очереди` : "плейбук";
    if (mode === "now" && targets.size > 30 && !window.confirm(`Запустить ${what} на ${pcCount(targets.size)}?`)) return;
    setBusy(true);
    try {
      if (mode === "now") {
        const { data } = await apiClient.post<{ task_run_id: string; waiting_hosts: number; host_count: number }>("/playbooks/run", {
          repo_id: repoId,
          playbook_names: chosen.map((f) => f.path),
          host_ids: hostIds,
          host_group_ids: groupIds,
          host_tag_ids: [...tagIds],
          extra_vars: varsToObject(vars),
          defer_offline: deferOffline,
        });
        chosen.forEach((f) => rememberPlaybook(f.key));
        queryClient.invalidateQueries({ queryKey: ["tasks"] });
        onDone?.();
        if (data.waiting_hosts > 0) toast({ tone: "info", message: waitingNotice(data.waiting_hosts, data.host_count) });
        openTask(data.task_run_id);
      } else {
        await apiClient.post("/playbooks/schedules", {
          repo_id: repoId,
          playbook_name: playbook,
          host_ids: hostIds,
          host_group_ids: groupIds,
          host_tag_ids: [...tagIds],
          extra_vars: varsToObject(vars),
          cron_expression: cron,
          enabled: true,
        });
        rememberPlaybook(chosen[0].key);
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
        <ol className="space-y-2">
          {selectedKeys.map((key, index) => {
            const file = selectedFiles[index];
            const several = selectedKeys.length > 1;
            return (
              <li key={index} className="flex items-center gap-2">
                {several && <span className="w-5 shrink-0 text-right text-xs tabular-nums text-subtle">{index + 1}.</span>}
                <div className="min-w-0 flex-1">
                  <PlaybookSelect files={catalog.files} value={key} onChange={(k) => setKeyAt(index, k)} loading={catalog.isLoading} />
                </div>
                {several && (
                  <>
                    <button type="button" className="btn-secondary px-1.5 disabled:opacity-40" onClick={() => move(index, -1)} disabled={index === 0} aria-label="Выполнить раньше" title="Раньше">
                      <ArrowUp className="h-4 w-4" />
                    </button>
                    <button type="button" className="btn-secondary px-1.5 disabled:opacity-40" onClick={() => move(index, 1)} disabled={index === selectedKeys.length - 1} aria-label="Выполнить позже" title="Позже">
                      <ArrowDown className="h-4 w-4" />
                    </button>
                    <button type="button" className="btn-secondary px-1.5" onClick={() => removeAt(index)} aria-label="Убрать плейбук" title="Убрать">
                      <X className="h-4 w-4" />
                    </button>
                  </>
                )}
                {canEdit && !file && <span className="w-[38px] shrink-0" aria-hidden />}
                {canEdit && file && (
                  <Link
                    to={`/automation/editor?repo=${file.repo_id}&path=${encodeURIComponent(file.path)}`}
                    className="btn-secondary px-2.5"
                    title={file.local ? "Открыть в редакторе" : "Открыть текст плейбука (из git — только просмотр и копия в локальные)"}
                    aria-label="Открыть плейбук в редакторе"
                  >
                    <FileCode2 className="h-4 w-4" />
                  </Link>
                )}
                {canEdit && index === 0 && (
                  <Link to="/automation/editor" className="btn-secondary px-2.5" title="Новый плейбук" aria-label="Новый плейбук">
                    <Plus className="h-4 w-4" />
                  </Link>
                )}
                {/* Поля всех строк одной ширины: у следующих строк на месте «+» — пустое место */}
                {canEdit && index > 0 && <span className="w-[38px] shrink-0" aria-hidden />}
              </li>
            );
          })}
        </ol>
        {chosen.length > 0 && (
          <div className="space-y-2">
            {chosen.map((f) => (
              <PlaybookDetails key={f.key} file={f} heading={chosen.length > 1 ? playbookLabel(f) : undefined} />
            ))}
          </div>
        )}
        {mode === "now" && chosen.length > 0 && selectedKeys.every(Boolean) && (
          <button
            type="button"
            className="inline-flex items-center gap-1.5 text-xs text-blue-600 hover:underline dark:text-blue-400"
            onClick={() => setSelectedKeys((prev) => [...prev, ""])}
          >
            <ListPlus className="h-3.5 w-3.5" />
            Добавить плейбук — выполнятся по очереди
          </button>
        )}
        {mixedSources && (
          <p className="flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400">
            <AlertTriangle className="h-3.5 w-3.5" />
            Плейбуки из разных источников запускаются отдельно — выберите плейбуки одного источника
          </p>
        )}
        {tooManyForSchedule && (
          <p className="flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400">
            <AlertTriangle className="h-3.5 w-3.5" />
            Расписание запускает один плейбук — оставьте один или запустите сейчас
          </p>
        )}
      </section>

      <section className="space-y-2">
        <label className="field-label mb-0">2. Хосты</label>
        <TagTargets value={tagIds} onChange={setTagIds} hosts={hosts} />
        <HostPicker value={selection} onChange={setSelection} height={pickerHeight} />
        {tagIds.size > 0 && (
          <p className="text-xs text-muted-foreground">
            {tagIds.size > 1 ? "Теги" : "Тег"} {[...tagIds].map((id) => `«${tagById.get(id)?.name ?? "…"}»`).join(", ")}: {pcCount(tagged.length)}
            {selection.size > 0 && ` + выбрано в дереве ${pcCount(selection.size)}, всего ${pcCount(targets.size)}`}
            {mode === "schedule" && " — теги раскрываются при каждом запуске, новые ПК с тегом попадут в расписание сами"}.
          </p>
        )}
        {offline > 0 && mode === "now" && (
          <div className="flex items-start gap-2.5 text-xs">
            <Switch checked={deferOffline} onChange={setDeferOffline} label="Запустить на выключенных ПК, когда они появятся в сети" />
            <p className={deferOffline ? "text-muted-foreground" : "flex items-center gap-1.5 text-amber-600 dark:text-amber-400"}>
              {!deferOffline && <AlertTriangle className="h-3.5 w-3.5 shrink-0" />}
              {offline} из {pcCount(targets.size)} сейчас не в сети.{" "}
              {deferOffline
                ? "На каждом из них задача запустится сама, когда он появится в сети (ждём до 7 дней)."
                : "На них запуск, скорее всего, завершится ошибкой."}
            </p>
          </div>
        )}
        {offline > 0 && mode === "schedule" && (
          <p className="flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400">
            <AlertTriangle className="h-3.5 w-3.5" />
            {offline} из {pcCount(targets.size)} сейчас не в сети — если при срабатывании расписания они будут выключены, запуск на них завершится ошибкой
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
            <p className="text-xs text-subtle">Выбранные группы и теги раскрываются при каждом запуске: новые ПК в аудитории или с тегом попадут в расписание сами.</p>
          </div>
        )}

        <ErrorText>{error}</ErrorText>
        <div className="flex flex-wrap items-center gap-3">
          <Button
            onClick={submit}
            loading={busy}
            disabled={!playbook || !hasTargets || mixedSources || tooManyForSchedule || (mode === "schedule" && !isValidCron(cron))}
          >
            {mode === "now" ? <Play className="h-4 w-4" /> : <CalendarClock className="h-4 w-4" />}
            {mode === "now"
              ? chosen.length > 1
                ? `Запустить ${chosen.length} плейбука на ${pcCount(targets.size)}`
                : `Запустить на ${pcCount(targets.size)}`
              : "Создать расписание"}
          </Button>
          {runAsHint && <span className="text-xs text-subtle">{runAsHint}</span>}
          {!playbook && <span className="text-xs text-subtle">Выберите плейбук</span>}
          {playbook && !hasTargets && <span className="text-xs text-subtle">Выберите хосты</span>}
        </div>
      </section>
    </div>
  );
}
