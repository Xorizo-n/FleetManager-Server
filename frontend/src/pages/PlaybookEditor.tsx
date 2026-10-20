import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, Copy, Lock, Play, Save, ShieldCheck, Trash2, XCircle } from "lucide-react";
import { apiClient } from "../api/client";
import { keys, useRepos } from "../api/queries";
import Button from "../components/ui/Button";
import { ErrorText, Loading } from "../components/ui/States";
import { useToast } from "../components/ui/Toast";
import { apiError, formatDateTime } from "../lib/format";

// CodeMirror нужен только здесь — отдельный чанк, остальной интерфейс его не грузит
const YamlEditor = lazy(() => import("../components/YamlEditor"));

interface PlaybookContent {
  repo_id: string;
  path: string;
  content: string;
  editable: boolean;
  modified_at: string | null;
}

type Check = { ok: true } | { ok: false; error: string } | null;

/** «Ошибка YAML (строка 12, позиция 3)» → 12: подсветить строку в редакторе */
const errorLineOf = (error: string | null | undefined) => {
  const m = error?.match(/строка (\d+)/) ?? error?.match(/line (\d+)/);
  return m ? Number(m[1]) : null;
};

/**
 * Редактор плейбука. Без параметров — новый локальный плейбук; ?repo=&path= — открыть файл:
 * локальный правится, из git только просматривается и копируется в локальные.
 */
export default function PlaybookEditor() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();
  const queryClient = useQueryClient();
  const repos = useRepos();
  const repoParam = params.get("repo");
  const pathParam = params.get("path");
  const isNew = !repoParam || !pathParam;

  const loaded = useQuery({
    queryKey: ["playbook-content", repoParam, pathParam],
    queryFn: () => apiClient.get<PlaybookContent>(`/playbooks/repos/${repoParam}/content`, { params: { path: pathParam } }).then((r) => r.data),
    enabled: !isNew,
  });
  const template = useQuery({
    queryKey: ["playbook-template"],
    queryFn: () => apiClient.get<{ content: string }>("/playbooks/local/template").then((r) => r.data.content),
    enabled: isNew,
    staleTime: Infinity,
  });

  const localRepo = repos.data?.find((r) => r.kind === "local");
  const sourceRepo = repos.data?.find((r) => r.id === repoParam);
  // Копия плейбука из git: тот же текст, но сохраняется уже как новый локальный
  const [copying, setCopying] = useState(false);
  const readOnly = !isNew && !copying && loaded.data?.editable === false;
  const editingLocal = !isNew && !copying && loaded.data?.editable === true;

  const [path, setPath] = useState("");
  const [content, setContent] = useState("");
  const [baseline, setBaseline] = useState<{ path: string; content: string } | null>(null);
  const [check, setCheck] = useState<Check>(null);
  const [busy, setBusy] = useState<"check" | "save" | "delete" | null>(null);

  useEffect(() => {
    if (isNew && template.data !== undefined && baseline === null) {
      setContent(template.data);
      setPath("");
      setBaseline({ path: "", content: template.data });
    }
  }, [isNew, template.data, baseline]);

  useEffect(() => {
    if (!isNew && loaded.data) {
      setContent(loaded.data.content);
      setPath(loaded.data.path);
      setBaseline({ path: loaded.data.path, content: loaded.data.content });
      setCopying(false);
      setCheck(null);
    }
  }, [isNew, loaded.data]);

  const dirty = !readOnly && baseline !== null && (copying || content !== baseline.content || path !== baseline.path);

  // Закрыть вкладку с несохранёнными правками — спросить
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  const leave = (to: string) => {
    if (dirty && !window.confirm("Изменения не сохранены. Уйти из редактора?")) return;
    navigate(to);
  };

  async function runCheck() {
    setBusy("check");
    try {
      const { data } = await apiClient.post<{ ok: boolean; error: string | null }>("/playbooks/local/check", { content });
      setCheck(data.ok ? { ok: true } : { ok: false, error: data.error ?? "Ошибка" });
    } catch (err) {
      setCheck({ ok: false, error: apiError(err, "Проверка не удалась") });
    } finally {
      setBusy(null);
    }
  }

  async function save() {
    if (readOnly || busy) return;
    if (!path.trim()) {
      setCheck({ ok: false, error: "Укажите имя файла, например install/firefox.yml" });
      return;
    }
    setBusy("save");
    try {
      const { data } = await apiClient.put<PlaybookContent>("/playbooks/local/file", {
        path: path.trim(),
        content,
        original_path: editingLocal ? baseline?.path : null,
      });
      if (localRepo) await queryClient.invalidateQueries({ queryKey: keys.files(localRepo.id) });
      queryClient.setQueryData(["playbook-content", data.repo_id, data.path], data);
      setBaseline({ path: data.path, content: data.content });
      setContent(data.content);
      setCheck({ ok: true });
      setCopying(false);
      toast({ tone: "success", message: `Плейбук ${data.path} сохранён` });
      setParams({ repo: data.repo_id, path: data.path }, { replace: true });
    } catch (err) {
      setCheck({ ok: false, error: apiError(err, "Не удалось сохранить плейбук") });
    } finally {
      setBusy(null);
    }
  }

  async function remove() {
    if (!editingLocal || !baseline) return;
    if (!window.confirm(`Удалить плейбук ${baseline.path}? Его нельзя будет восстановить.`)) return;
    setBusy("delete");
    try {
      await apiClient.delete("/playbooks/local/file", { params: { path: baseline.path } });
      if (localRepo) await queryClient.invalidateQueries({ queryKey: keys.files(localRepo.id) });
      toast({ tone: "success", message: `Плейбук ${baseline.path} удалён` });
      navigate("/automation");
    } catch (err) {
      setCheck({ ok: false, error: apiError(err, "Не удалось удалить плейбук") });
    } finally {
      setBusy(null);
    }
  }

  const title = isNew ? "Новый плейбук" : copying ? "Копия плейбука" : (loaded.data?.path ?? pathParam ?? "Плейбук");
  const errorLine = useMemo(() => (check && !check.ok ? errorLineOf(check.error) : null), [check]);
  const ready = isNew ? template.data !== undefined : !!loaded.data;
  const runLink = !dirty && editingLocal && baseline ? `/automation?tab=run&repo=${loaded.data?.repo_id}&playbook=${encodeURIComponent(baseline.path)}` : null;

  if (!isNew && loaded.error) {
    return (
      <div className="space-y-4">
        <button type="button" onClick={() => leave("/automation")} className="btn-ghost btn-sm">
          <ArrowLeft className="h-3.5 w-3.5" />
          Автоматизация
        </button>
        <ErrorText>{apiError(loaded.error, "Не удалось открыть плейбук")}</ErrorText>
      </div>
    );
  }

  return (
    <div className="animate-fade-in space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <button type="button" onClick={() => leave("/automation")} className="btn-ghost btn-sm -ml-2.5">
            <ArrowLeft className="h-3.5 w-3.5" />
            Автоматизация
          </button>
          <h1 className="truncate text-xl font-semibold text-foreground">
            {title}
            {dirty && <span className="ml-2 align-middle text-xs font-normal text-amber-600 dark:text-amber-400">не сохранён</span>}
          </h1>
          <p className="text-sm text-muted-foreground">
            {readOnly
              ? `Из git-репозитория «${sourceRepo?.name ?? "—"}» — только просмотр. Правьте его в git или сохраните копию в локальные.`
              : <>Локальный плейбук: хранится только на этом сервере. Перед сохранением проверяются YAML и <code className="font-mono text-xs">ansible-playbook --syntax-check</code>.</>}
            {editingLocal && loaded.data?.modified_at && ` Изменён ${formatDateTime(loaded.data.modified_at)}.`}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {runLink && (
            <Link to={runLink} className="btn-secondary">
              <Play className="h-4 w-4" />
              Запустить
            </Link>
          )}
          {readOnly ? (
            <Button
              onClick={() => {
                setCopying(true);
                setCheck(null);
              }}
            >
              <Copy className="h-4 w-4" />
              Сохранить копию в локальные
            </Button>
          ) : (
            <>
              <Button variant="secondary" onClick={runCheck} loading={busy === "check"} disabled={!ready || !!busy}>
                {busy !== "check" && <ShieldCheck className="h-4 w-4" />}
                Проверить
              </Button>
              <Button onClick={save} loading={busy === "save"} disabled={!ready || !!busy || !dirty} title="Ctrl+S">
                {busy !== "save" && <Save className="h-4 w-4" />}
                Сохранить
              </Button>
            </>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-[16rem] max-w-xl flex-1">
          <label htmlFor="playbook-path" className="field-label">
            Файл
          </label>
          <div className="relative">
            <input
              id="playbook-path"
              value={path}
              onChange={(e) => {
                setPath(e.target.value);
                setCheck(null);
              }}
              readOnly={readOnly}
              placeholder="install/firefox.yml"
              spellCheck={false}
              autoComplete="off"
              className={`input-base pr-9 font-mono ${readOnly ? "text-muted-foreground" : ""}`}
            />
            {readOnly && <Lock className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-subtle" />}
          </div>
          {!readOnly && <p className="mt-1 text-xs text-subtle">Латиница, цифры, «_» и «-», окончание .yml; можно одну папку — она станет группой в каталоге</p>}
        </div>
        {editingLocal && (
          <Button variant="ghost" onClick={remove} loading={busy === "delete"} disabled={!!busy} className="text-rose-600 hover:text-rose-700 dark:text-rose-400">
            {busy !== "delete" && <Trash2 className="h-4 w-4" />}
            Удалить
          </Button>
        )}
      </div>

      {check && (
        <div
          role="status"
          className={`flex items-start gap-2.5 rounded-lg border px-3 py-2.5 text-sm ${
            check.ok
              ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-700 dark:text-emerald-400"
              : "border-rose-500/30 bg-rose-500/5 text-rose-700 dark:text-rose-300"
          }`}
        >
          {check.ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0" />}
          {check.ok ? (
            <span>Ошибок не найдено: YAML и <code className="font-mono text-xs">ansible-playbook --syntax-check</code> в порядке</span>
          ) : (
            <pre className="min-w-0 flex-1 whitespace-pre-wrap break-words font-mono text-xs leading-relaxed">{check.error}</pre>
          )}
        </div>
      )}
      <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-panel">
        {ready ? (
          <Suspense fallback={<Loading label="Загрузка редактора…" className="h-[60vh]" />}>
            <YamlEditor
              value={content}
              onChange={(v) => {
                setContent(v);
                if (check) setCheck(null);
              }}
              readOnly={readOnly}
              onSave={save}
              errorLine={errorLine}
              className="h-[calc(100vh-22rem)] min-h-[24rem]"
            />
          </Suspense>
        ) : (
          <Loading label="Загрузка плейбука…" className="h-[60vh]" />
        )}
      </div>

    </div>
  );
}
