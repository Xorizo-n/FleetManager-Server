import { ReactNode, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, X } from "lucide-react";
import { apiClient } from "../../api/client";
import { keys, useCanEdit, useFleet, useRolloutAssignees, useRollouts, useTasks } from "../../api/queries";
import type { RolloutItem, RolloutItemStatus, RolloutProgress, RolloutRequest, RolloutStatus } from "../../api/types";
import PageHeader from "../../components/ui/PageHeader";
import Badge from "../../components/ui/Badge";
import Button from "../../components/ui/Button";
import Modal from "../../components/ui/Modal";
import SearchInput from "../../components/ui/SearchInput";
import { Empty, ErrorText, Loading } from "../../components/ui/States";
import { useToast } from "../../components/ui/Toast";
import { useOpenTask } from "../../components/TaskPanel";
import { apiError, formatDateTime, pcCount, playbookShortName, STATUS_LABELS } from "../../lib/format";

type Tone = "success" | "danger" | "info" | "warning" | "neutral" | "waiting";

export const ROLLOUT_STATUS: Record<RolloutStatus, { label: string; tone: Tone }> = {
  new: { label: "Новая", tone: "neutral" },
  in_progress: { label: "В работе", tone: "info" },
  blocked: { label: "Заблокирована", tone: "warning" },
  done: { label: "Выполнена", tone: "success" },
  cancelled: { label: "Отменена", tone: "neutral" },
};

const ITEM_STATUS: Record<RolloutItemStatus, { label: string; dot: string }> = {
  todo: { label: "Не начато", dot: "bg-slate-300 dark:bg-slate-600" },
  in_progress: { label: "В работе", dot: "bg-sky-500" },
  blocked: { label: "Блокер", dot: "bg-amber-500" },
  done: { label: "Готово", dot: "bg-emerald-500" },
};

const ACTIVE: RolloutStatus[] = ["new", "in_progress", "blocked"];

/** Доли полосы готовности: стоит, идёт / ждёт включения, ошибка, не запускалось */
const PROGRESS_PARTS: { key: keyof Omit<RolloutProgress, "total">; label: string; bar: string }[] = [
  { key: "done", label: "стоит", bar: "bg-emerald-500" },
  { key: "active", label: "идёт или ждёт включения", bar: "bg-violet-400 dark:bg-violet-500" },
  { key: "failed", label: "ошибка", bar: "bg-rose-500" },
  { key: "not_started", label: "не запускалось", bar: "bg-slate-300 dark:bg-slate-600" },
];

function progressTitle(p: RolloutProgress) {
  return PROGRESS_PARTS.filter((part) => p[part.key]).map((part) => `${part.label}: ${p[part.key]}`).join(", ");
}

/** «Готово N из M ПК» с полосой долей. */
function ProgressBar({ progress, className = "" }: { progress: RolloutProgress; className?: string }) {
  const pct = progress.total ? Math.round((progress.done / progress.total) * 100) : 0;
  return (
    <div className={`space-y-1 ${className}`} title={progressTitle(progress)}>
      <div className="flex items-baseline justify-between gap-2 text-xs tabular-nums">
        <span className="text-foreground">{progress.done} из {pcCount(progress.total)}</span>
        <span className="text-subtle">{pct}%</span>
      </div>
      <div className="flex h-1.5 overflow-hidden rounded-full bg-muted" role="img" aria-label={`Готово ${progress.done} из ${progress.total} ПК. ${progressTitle(progress)}`}>
        {PROGRESS_PARTS.map((part) =>
          progress[part.key] ? <span key={part.key} className={`${part.bar} h-full`} style={{ width: `${(progress[part.key] / progress.total) * 100}%` }} /> : null,
        )}
      </div>
    </div>
  );
}

/** Дата без времени (срок): показываем как есть, без сдвига часового пояса. */
function formatDay(day: string | null) {
  return day ? new Date(`${day}T00:00:00Z`).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", timeZone: "UTC" }) : "—";
}

function isOverdue(r: RolloutRequest) {
  return !!r.due_date && ACTIVE.includes(r.status) && r.due_date < new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Yekaterinburg" });
}

function itemTitle(i: RolloutItem) {
  return [ITEM_STATUS[i.status].label, i.progress && `${i.progress.done} из ${pcCount(i.progress.total)}`, i.note].filter(Boolean).join(" — ");
}

export default function Rollouts({ tabs }: { tabs: ReactNode }) {
  const canEdit = useCanEdit();
  const { data, isLoading } = useRollouts();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<string>("active");
  const [editing, setEditing] = useState<RolloutRequest | "new" | null>(null);

  const list = data ?? [];
  const counts = useMemo(() => {
    const c: Partial<Record<RolloutStatus, number>> = {};
    list.forEach((r) => (c[r.status] = (c[r.status] ?? 0) + 1));
    return c;
  }, [list]);
  const overdue = list.filter(isOverdue).length;

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return list.filter((r) => {
      if (status === "active" ? !ACTIVE.includes(r.status) : status && r.status !== status) return false;
      if (!q) return true;
      return [r.partner, r.course, r.rooms, r.schedule, r.assignee_name, r.notes, ...r.items.map((i) => i.software)]
        .filter(Boolean).join(" ").toLowerCase().includes(q);
    });
  }, [list, search, status]);

  const summary = [
    counts.in_progress && `в работе: ${counts.in_progress}`,
    counts.blocked && `заблокировано: ${counts.blocked}`,
    counts.new && `новых: ${counts.new}`,
    counts.done && `выполнено: ${counts.done}`,
    overdue > 0 && `просрочено: ${overdue}`,
  ].filter(Boolean).join(" · ");

  return (
    <div className="animate-fade-in space-y-4">
      <PageHeader
        title="Задачи"
        description={summary ? `Заявки на раскатку ПО — ${summary}` : "Заявки отдела на установку ПО: что, где и к какому занятию поставить"}
        actions={canEdit && (
          <Button size="sm" onClick={() => setEditing("new")}>
            <Plus className="h-3.5 w-3.5" />
            Новая заявка
          </Button>
        )}
      />
      {tabs}
      <div className="flex flex-wrap items-center gap-2">
        <SearchInput value={search} onChange={setSearch} placeholder="Курс, партнёр, аудитория, программа" className="min-w-[220px] flex-1" />
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="input-base w-auto py-2" aria-label="Статус заявки">
          <option value="active">Незакрытые</option>
          <option value="">Все заявки</option>
          {(Object.keys(ROLLOUT_STATUS) as RolloutStatus[]).map((s) => <option key={s} value={s}>{ROLLOUT_STATUS[s].label}</option>)}
        </select>
      </div>

      <div className="table-shell">
        <table className="table-base">
          <thead>
            <tr>
              <th>Курс</th>
              <th>Аудитории</th>
              <th>Программы</th>
              <th>Готово</th>
              <th>Ответственный</th>
              <th>Статус</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const doneItems = r.items.filter((i) => i.status === "done").length;
              return (
                <tr
                  key={r.id}
                  tabIndex={0}
                  className="is-interactive align-top"
                  onClick={() => setEditing(r)}
                  onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), setEditing(r))}
                >
                  <td className="max-w-[300px]">
                    {r.partner && <div className="truncate text-xs text-subtle">{r.partner}</div>}
                    <div className="line-clamp-2 font-medium text-foreground">{r.course}</div>
                  </td>
                  <td className="max-w-[180px] text-muted-foreground">
                    <div className="truncate text-foreground">{r.rooms ?? "—"}</div>
                    {r.schedule && <div className="truncate text-xs">{r.schedule}</div>}
                  </td>
                  <td className="max-w-[340px]">
                    <div className="flex flex-wrap gap-1">
                      {r.items.map((i, n) => (
                        <span key={i.id ?? n} className="inline-flex items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 text-xs text-foreground" title={itemTitle(i)}>
                          <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${ITEM_STATUS[i.status].dot}`} />
                          {i.software}
                          {i.progress && i.status !== "done" && <span className="tabular-nums text-subtle">{i.progress.done}/{i.progress.total}</span>}
                        </span>
                      ))}
                      {r.items.length === 0 && <span className="text-subtle">—</span>}
                    </div>
                  </td>
                  <td className="whitespace-nowrap">
                    <div className="w-32 space-y-1">
                      {r.progress && <ProgressBar progress={r.progress} />}
                      {r.items.length > 0 && <div className="text-xs tabular-nums text-subtle">программ: {doneItems} из {r.items.length}</div>}
                      {r.items.length === 0 && "—"}
                    </div>
                  </td>
                  <td className="whitespace-nowrap text-muted-foreground">
                    <div className="text-foreground">{r.assignee_name ?? "—"}</div>
                    {r.due_date && (
                      <div className={`text-xs ${isOverdue(r) ? "font-medium text-rose-600 dark:text-rose-400" : ""}`}>
                        до {formatDay(r.due_date)}{isOverdue(r) && " · просрочено"}
                      </div>
                    )}
                  </td>
                  <td>
                    <Badge status={r.status} tone={ROLLOUT_STATUS[r.status].tone}>{ROLLOUT_STATUS[r.status].label}</Badge>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {isLoading && <Loading />}
        {!isLoading && rows.length === 0 && (
          <Empty>{list.length === 0 ? "Заявок пока нет — добавьте первую кнопкой «Новая заявка»" : "Под фильтр ничего не подходит"}</Empty>
        )}
      </div>
      {editing && <RolloutEditor request={editing === "new" ? null : editing} canEdit={canEdit} onClose={() => setEditing(null)} />}
    </div>
  );
}

const EMPTY_ITEM: RolloutItem = { software: "", rooms: null, status: "todo", note: null, host_group_ids: [], task_run_ids: [] };

/** Выбранные значения — плашками с крестиком, добавление — из выпадающего списка. */
function ChipPicker({ label, value, options, disabled, onChange, onOpen }: {
  label: string;
  value: string[];
  options: { id: string; label: string }[];
  disabled: boolean;
  onChange: (ids: string[]) => void;
  onOpen?: (id: string) => void;
}) {
  const byId = new Map(options.map((o) => [o.id, o.label]));
  const rest = options.filter((o) => !value.includes(o.id));
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {value.map((id) => (
        <span key={id} className="inline-flex max-w-full items-center gap-1 rounded-md bg-muted px-2 py-1 text-xs text-foreground">
          {onOpen ? (
            <button type="button" className="truncate hover:underline" onClick={() => onOpen(id)} title="Открыть лог">{byId.get(id) ?? "удалённый объект"}</button>
          ) : (
            <span className="truncate">{byId.get(id) ?? "удалённый объект"}</span>
          )}
          {!disabled && (
            <button type="button" className="text-subtle hover:text-foreground" onClick={() => onChange(value.filter((v) => v !== id))} aria-label={`Убрать: ${byId.get(id) ?? id}`}>
              <X className="h-3 w-3" />
            </button>
          )}
        </span>
      ))}
      {!disabled && rest.length > 0 && (
        <select className="input-base w-auto max-w-full py-1 text-xs" aria-label={label} value="" onChange={(e) => e.target.value && onChange([...value, e.target.value])}>
          <option value="">{label}</option>
          {rest.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
        </select>
      )}
      {disabled && value.length === 0 && <span className="text-xs text-subtle">—</span>}
    </div>
  );
}

function RolloutEditor({ request, canEdit, onClose }: { request: RolloutRequest | null; canEdit: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const openTask = useOpenTask();
  const assignees = useRolloutAssignees();
  const { groups, tree } = useFleet();
  const runs = useTasks({ task_type: "playbook", limit: 200 }, false);
  const [form, setForm] = useState(() => ({
    partner: request?.partner ?? "",
    course: request?.course ?? "",
    rooms: request?.rooms ?? "",
    schedule: request?.schedule ?? "",
    requirements: request?.requirements ?? "",
    status: request?.status ?? ("new" as RolloutStatus),
    assignee_id: request?.assignee_id ?? "",
    due_date: request?.due_date ?? "",
    notes: request?.notes ?? "",
  }));
  const [items, setItems] = useState<RolloutItem[]>(() => (request?.items.length ? request.items : [{ ...EMPTY_ITEM }]));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const field = (name: keyof typeof form) => ({
    value: form[name],
    disabled: !canEdit,
    onChange: (e: { target: { value: string } }) => setForm((f) => ({ ...f, [name]: e.target.value })),
  });
  const setItem = (n: number, patch: Partial<RolloutItem>) => setItems((list) => list.map((i, k) => (k === n ? { ...i, ...patch } : i)));

  const groupOptions = useMemo(
    () => groups.map((g) => ({ id: g.id, label: `${tree.pathOf(g.id)} · ${pcCount(tree.byId.get(g.id)?.hostIds.length ?? 0)}` }))
      .sort((a, b) => a.label.localeCompare(b.label, "ru")),
    [groups, tree],
  );
  // Привязанные запуски могут быть старше последних 200 — они всё равно должны подписываться
  const runOptions = useMemo(() => {
    const label = (name: string | null, created: string | null, hosts: number, status: string) =>
      `${playbookShortName(name ?? "")} · ${formatDateTime(created)} · ${pcCount(hosts)} · ${STATUS_LABELS[status] ?? status}`;
    const options = (runs.data ?? []).map((t) => ({ id: t.id, label: label(t.playbook_name, t.created_at, t.host_ids.length, t.status) }));
    for (const item of request?.items ?? []) {
      for (const r of item.runs ?? []) {
        if (!options.some((o) => o.id === r.id)) options.push({ id: r.id, label: label(r.playbook_name, r.created_at, r.host_count, r.status) });
      }
    }
    return options;
  }, [runs.data, request]);

  async function save() {
    setBusy(true);
    setError(null);
    const body = {
      ...form,
      assignee_id: form.assignee_id || null,
      due_date: form.due_date || null,
      items: items
        .filter((i) => i.software.trim())
        .map(({ software, rooms, status, note, host_group_ids, task_run_ids }) => ({ software, rooms, status, note, host_group_ids, task_run_ids })),
    };
    try {
      if (request) await apiClient.patch(`/rollouts/${request.id}`, body);
      else await apiClient.post("/rollouts", body);
      queryClient.invalidateQueries({ queryKey: keys.rollouts });
      toast({ tone: "success", message: request ? "Заявка сохранена" : "Заявка добавлена" });
      onClose();
    } catch (err) {
      setError(apiError(err, "Не удалось сохранить заявку"));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!request || !window.confirm(`Удалить заявку «${request.course}»?`)) return;
    try {
      await apiClient.delete(`/rollouts/${request.id}`);
      queryClient.invalidateQueries({ queryKey: keys.rollouts });
      toast({ tone: "success", message: "Заявка удалена" });
      onClose();
    } catch (err) {
      setError(apiError(err, "Не удалось удалить заявку"));
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title={request ? request.course : "Новая заявка на раскатку"}
      footer={
        <>
          <ErrorText>{error}</ErrorText>
          {canEdit && request && (
            <Button variant="secondary" onClick={remove} className="mr-auto">
              <Trash2 className="h-3.5 w-3.5" />
              Удалить
            </Button>
          )}
          <Button variant="secondary" onClick={onClose}>{canEdit ? "Отмена" : "Закрыть"}</Button>
          {canEdit && <Button onClick={save} loading={busy} disabled={!form.course.trim()}>Сохранить</Button>}
        </>
      }
    >
      <div className="space-y-5">
        {request?.progress && (
          <div className="rounded-lg border border-border p-3">
            <div className="mb-1 text-xs text-muted-foreground">Готово по всем программам с подсчётом по ПК</div>
            <ProgressBar progress={request.progress} />
          </div>
        )}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label className="field-label" htmlFor="ro-partner">Партнёр</label>
            <input id="ro-partner" className="input-base" placeholder="Фирма «1С», Контур…" {...field("partner")} />
          </div>
          <div>
            <label className="field-label" htmlFor="ro-course">Курс</label>
            <input id="ro-course" className="input-base" required {...field("course")} />
          </div>
          <div>
            <label className="field-label" htmlFor="ro-rooms">Аудитории</label>
            <input id="ro-rooms" className="input-base" placeholder="K-103, K-118" {...field("rooms")} />
          </div>
          <div>
            <label className="field-label" htmlFor="ro-schedule">Когда занятия</label>
            <input id="ro-schedule" className="input-base" placeholder="Вторник, 3 пара" {...field("schedule")} />
          </div>
          <div>
            <label className="field-label" htmlFor="ro-status">Статус</label>
            <select id="ro-status" className="input-base" {...field("status")}>
              {(Object.keys(ROLLOUT_STATUS) as RolloutStatus[]).map((s) => <option key={s} value={s}>{ROLLOUT_STATUS[s].label}</option>)}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="field-label" htmlFor="ro-assignee">Ответственный</label>
              <select id="ro-assignee" className="input-base" {...field("assignee_id")}>
                <option value="">Не назначен</option>
                {(assignees.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                {request?.assignee_id && !assignees.data?.some((a) => a.id === request.assignee_id) && (
                  <option value={request.assignee_id}>{request.assignee_name ?? "—"}</option>
                )}
              </select>
            </div>
            <div>
              <label className="field-label" htmlFor="ro-due">Срок</label>
              <input id="ro-due" type="date" className="input-base" {...field("due_date")} />
            </div>
          </div>
          <div className="sm:col-span-2">
            <label className="field-label" htmlFor="ro-req">Требования партнёра</label>
            <textarea id="ro-req" rows={3} className="input-base" placeholder="Как в заявке: версии, ссылки, лицензии" {...field("requirements")} />
          </div>
        </div>

        <div>
          <div className="mb-1 flex items-center justify-between">
            <span className="field-label mb-0">Программы</span>
            {canEdit && (
              <Button size="sm" variant="secondary" onClick={() => setItems((list) => [...list, { ...EMPTY_ITEM }])}>
                <Plus className="h-3.5 w-3.5" />
                Добавить
              </Button>
            )}
          </div>
          <p className="mb-2 text-xs text-subtle">
            Готовность считается по ПК выбранных аудиторий: ПК готов, если хотя бы один из привязанных запусков прошёл на нём успешно.
            Статус программы и заявки обновляется сам; «Блокер» и отмену ставите вы.
          </p>
          <div className="space-y-2">
            {items.map((item, n) => (
              <div key={item.id ?? `new-${n}`} className="space-y-2 rounded-lg border border-border p-3">
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-[2fr_1fr_1fr_auto]">
                  <input className="input-base" placeholder="Программа и версия" aria-label="Программа" disabled={!canEdit}
                    value={item.software} onChange={(e) => setItem(n, { software: e.target.value })} />
                  <input className="input-base" placeholder="Где, если не везде" aria-label="Подпись аудиторий программы" disabled={!canEdit}
                    value={item.rooms ?? ""} onChange={(e) => setItem(n, { rooms: e.target.value || null })} />
                  <select className="input-base" aria-label="Статус программы" disabled={!canEdit}
                    value={item.status} onChange={(e) => setItem(n, { status: e.target.value as RolloutItemStatus })}>
                    {(Object.keys(ITEM_STATUS) as RolloutItemStatus[]).map((s) => <option key={s} value={s}>{ITEM_STATUS[s].label}</option>)}
                  </select>
                  {canEdit && (
                    <button className="action-danger self-center" onClick={() => setItems((list) => list.filter((_, k) => k !== n))} aria-label="Убрать программу" title="Убрать">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
                <input className="input-base" placeholder="Комментарий: что мешает, что осталось" aria-label="Комментарий" disabled={!canEdit}
                  value={item.note ?? ""} onChange={(e) => setItem(n, { note: e.target.value || null })} />
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-[7rem_1fr] sm:items-center">
                  <span className="text-xs text-muted-foreground">Аудитории ПК</span>
                  <ChipPicker label="+ аудитория" value={item.host_group_ids} options={groupOptions} disabled={!canEdit}
                    onChange={(ids) => setItem(n, { host_group_ids: ids })} />
                  <span className="text-xs text-muted-foreground">Запуски</span>
                  <ChipPicker label="+ запуск плейбука" value={item.task_run_ids} options={runOptions} disabled={!canEdit}
                    onChange={(ids) => setItem(n, { task_run_ids: ids })} onOpen={openTask} />
                </div>
                {item.progress && item.id && request?.items.some((i) => i.id === item.id) && <ProgressBar progress={item.progress} />}
              </div>
            ))}
            {items.length === 0 && <Empty className="py-4">Программ нет</Empty>}
          </div>
        </div>

        <div>
          <label className="field-label" htmlFor="ro-notes">Заметки</label>
          <textarea id="ro-notes" rows={3} className="input-base" placeholder="Ход работ, договорённости, что ждём" {...field("notes")} />
        </div>
        {request && (
          <p className="text-xs text-subtle">
            Создал {request.created_by_name ?? "—"} {formatDateTime(request.created_at)} · изменена {formatDateTime(request.updated_at)}
          </p>
        )}
      </div>
    </Modal>
  );
}
