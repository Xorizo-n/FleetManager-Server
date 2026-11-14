import { useId, useMemo, useRef, useState } from "react";
import { isAxiosError } from "axios";
import { useQueryClient } from "@tanstack/react-query";
import { Check, ImageOff } from "lucide-react";
import { apiClient } from "../api/client";
import { keys, useFleet, useWallpaperAssignments, useWallpapers } from "../api/queries";
import type { Wallpaper, WallpaperKind } from "../api/types";
import Modal from "./ui/Modal";
import Button from "./ui/Button";
import { ErrorText } from "./ui/States";
import { useToast } from "./ui/Toast";
import HostPicker from "./HostPicker";
import { apiError, pcCount, plural } from "../lib/format";
import { KIND_LABELS, KINDS } from "../lib/wallpapers";

type Choice = { mode: "keep" } | { mode: "clear" } | { mode: "set"; id: string };

interface Props {
  initialHostIds?: string[];
  initialWallpaperId?: string;
  onClose: () => void;
}

/** Массовая замена обоев: что поставить, на какие ПК или группы и когда. */
export default function WallpaperAssignDialog({ initialHostIds = [], initialWallpaperId, onClose }: Props) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { tree } = useFleet();
  const catalog = useWallpapers();
  const assignments = useWallpaperAssignments();
  const [choices, setChoices] = useState<Record<WallpaperKind, Choice>>({
    desktop: initialWallpaperId ? { mode: "set", id: initialWallpaperId } : { mode: "keep" },
    lock_screen: { mode: "keep" },
  });
  const [selection, setSelection] = useState<Set<string>>(() => new Set(initialHostIds));
  const [scope, setScope] = useState<"hosts" | "groups">("hosts");
  const [selectedGroups, setSelectedGroups] = useState<string[]>([]);
  const [when, setWhen] = useState<"now" | "later">("now");
  const [at, setAt] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [timeError, setTimeError] = useState<string | null>(null);
  const [editingKind, setEditingKind] = useState<WallpaperKind | null>(null);
  const timeId = useId();

  const groupIds = scope === "groups" ? selectedGroups : [];
  const hostIds = scope === "hosts" ? [...selection] : [];
  const targetCount = scope === "hosts" ? selection.size : new Set(groupIds.flatMap((id) => tree.byId.get(id)?.hostIds ?? [])).size;
  const targetLabel = scope === "hosts" ? pcCount(targetCount) : plural(groupIds.length, "группу", "группы", "групп");
  const noTargets = hostIds.length + groupIds.length === 0;
  const nothingChosen = KINDS.every((k) => choices[k].mode === "keep");
  const removingOnly = !nothingChosen && KINDS.every((k) => choices[k].mode !== "set");
  const changes = KINDS.flatMap((kind) => {
    const choice = choices[kind];
    if (choice.mode === "keep") return [];
    const description = choice.mode === "clear" ? "снять назначение" : catalog.data?.find((w) => w.id === choice.id)?.name ?? "изображение недоступно";
    return [`${KIND_LABELS[kind]} — ${description}`];
  });
  const missingImage = KINDS.some((kind) => {
    const choice = choices[kind];
    return choice.mode === "set" && !catalog.data?.some((w) => w.id === choice.id);
  });

  // Назначение группы снимает свои назначения её аудиторий и ПК (backend: services/wallpapers.apply_assignment)
  const replaced = useMemo(() => {
    const kinds = KINDS.filter((k) => choices[k].mode !== "keep");
    const nestedGroups = new Set<string>();
    const hostIds = new Set<string>();
    for (const gid of selectedGroups) {
      tree.descendants(gid).forEach((d) => d !== gid && nestedGroups.add(d));
      tree.byId.get(gid)?.hostIds.forEach((h) => hostIds.add(h));
    }
    return (assignments.data ?? []).filter((a) => kinds.includes(a.kind) && (
      (a.group_id && nestedGroups.has(a.group_id)) || (a.host_id && hostIds.has(a.host_id))
    )).length;
  }, [choices, selectedGroups, tree, assignments.data]);
  const impactPending = groupIds.length > 0 && (assignments.isLoading || assignments.isError);
  const atDate = at ? new Date(at) : null;
  const dateError = when === "later" ? timeError ?? (at && !(atDate && atDate.getTime() > Date.now()) ? "Укажите время смены в будущем" : null) : null;
  const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;

  const value = (choice: Choice) => (choice.mode === "set" ? choice.id : choice.mode === "clear" ? "clear" : null);

  async function submit() {
    if (busy || nothingChosen || noTargets || impactPending || missingImage) return;
    if (when === "later" && !(atDate && atDate.getTime() > Date.now())) {
      setTimeError("Укажите время смены в будущем");
      return;
    }
    setBusy(true);
    setError(null);
    setTimeError(null);
    try {
      const { data } = await apiClient.post<{ changed: number; schedule_id: string | null }>("/wallpapers/assign", {
        host_ids: hostIds,
        group_ids: groupIds,
        desktop: value(choices.desktop),
        lock_screen: value(choices.lock_screen),
        apply_at: when === "later" && atDate ? atDate.toISOString() : null,
        comment: comment.trim() || null,
      });
      queryClient.invalidateQueries({ queryKey: ["wallpapers"] });
      queryClient.invalidateQueries({ queryKey: keys.hosts });
      toast({
        tone: "success",
        message: data.schedule_id
          ? `Смена обоев запланирована на ${atDate!.toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" })}`
          : `Назначения обновлены (${targetLabel}). Агенты применят изменения в течение 5 минут, выключенные ПК — после включения`,
      });
      onClose();
    } catch (err) {
      const detail = isAxiosError(err) ? err.response?.data?.detail : undefined;
      const dateIssue = Array.isArray(detail) && detail.some((issue) => issue.loc?.includes("apply_at"));
      if (when === "later" && (dateIssue || detail === "Укажите время смены в будущем")) {
        setTimeError(apiError(err, "Укажите время смены в будущем"));
      } else {
        setError(apiError(err, "Не удалось назначить обои"));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title="Обои рабочего стола и экрана блокировки"
      footer={
        <div className="w-full space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
            <div className="min-w-0 flex-1 break-words text-sm">
              <p className="font-medium text-foreground">{changes.join(" · ") || "Выберите, что изменить"}</p>
              <p className="text-muted-foreground">
                {noTargets ? "Получатели не выбраны" : scope === "hosts" ? pcCount(targetCount) :
                  `${groupIds.slice(0, 2).map((id) => tree.pathOf(id)).join(", ")}${groupIds.length > 2 ? ` и ещё ${groupIds.length - 2}` : ""} (${pcCount(targetCount)} сейчас и будущие ПК)`}
                {" · "}{when === "now" ? "Сейчас" : atDate && !dateError ? atDate.toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" }) : "Укажите время смены"}
              </p>
            </div>
            <Button onClick={submit} loading={busy} disabled={nothingChosen || noTargets || impactPending || missingImage || (when === "later" && (!at || !!dateError))}>
              {when === "later" ? "Запланировать" : removingOnly ? "Снять назначения" : "Назначить обои"}
            </Button>
          </div>
          {groupIds.length > 0 && replaced > 0 && (
            <p className="text-sm text-amber-700 dark:text-amber-400">
              Снятие назначений у подгрупп и ПК: {plural(replaced, "локальное назначение", "локальных назначения", "локальных назначений")}.
            </p>
          )}
          <ErrorText>{error}</ErrorText>
        </div>
      }
    >
      <div className="space-y-5">
        <section aria-label="Что изменить" className="divide-y divide-border border-y border-border">
          {KINDS.map((kind) => (
            <WallpaperChoice
              key={kind}
              label={KIND_LABELS[kind]}
              catalog={catalog}
              value={choices[kind]}
              expanded={editingKind === kind}
              onToggle={() => setEditingKind((current) => current === kind ? null : kind)}
              onChange={(choice) => setChoices((prev) => ({ ...prev, [kind]: choice }))}
            />
          ))}
        </section>

        <section>
          <fieldset className="mb-3">
            <legend className="mb-2 text-sm font-semibold text-foreground">Кому назначить</legend>
            <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm">
              <label className="flex items-center gap-2"><input type="radio" name="wallpaper-scope" checked={scope === "hosts"} onChange={() => setScope("hosts")} />Текущие ПК</label>
              <label className="flex items-center gap-2"><input type="radio" name="wallpaper-scope" checked={scope === "groups"} onChange={() => setScope("groups")} />Вся группа</label>
            </div>
          </fieldset>
          {scope === "hosts" ? <HostPicker value={selection} onChange={setSelection} height={220} /> : (
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">Правило охватит текущие и будущие ПК выбранных групп. Локальные назначения того же вида в подгруппах и на ПК будут сняты.</p>
              <label className="block text-sm">
                Добавить группу
                <select className="input-base mt-1" value="" onChange={(e) => {
                  const id = e.target.value;
                  const descendants = tree.descendants(id);
                  setSelectedGroups((prev) => [...prev.filter((group) => !descendants.has(group)), id]);
                }}>
                  <option value="" disabled>Корпус, этаж или аудитория</option>
                  {tree.options.map(({ id, label }) => (
                    <option key={id} value={id} disabled={selectedGroups.some((group) => tree.descendants(group).has(id))}>{label}</option>
                  ))}
                </select>
              </label>
              {groupIds.length > 0 && <ul className="divide-y divide-border">
                {groupIds.map((id) => <li key={id} className="flex items-center justify-between gap-3 py-1 text-sm">
                  <span>{tree.pathOf(id)}</span>
                  <Button size="sm" variant="secondary" aria-label={`Убрать ${tree.pathOf(id)} из выбора`} onClick={() => setSelectedGroups((prev) => prev.filter((group) => group !== id))}>Убрать</Button>
                </li>)}
              </ul>}
              {assignments.isLoading && <p className="text-sm text-muted-foreground">Проверяем локальные назначения…</p>}
              {assignments.isError && <div className="space-y-1">
                <ErrorText>Не удалось проверить локальные назначения.</ErrorText>
                <Button size="sm" variant="secondary" loading={assignments.isFetching} onClick={() => assignments.refetch()}>Повторить</Button>
              </div>}
            </div>
          )}
        </section>

        <section className="space-y-2">
          <h3 className="text-sm font-semibold text-foreground">Когда</h3>
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <label className="flex cursor-pointer items-center gap-2">
              <input type="radio" name={`${timeId}-when`} className="accent-blue-600" checked={when === "now"} onChange={() => setWhen("now")} />
              Сейчас
            </label>
            <label className="flex cursor-pointer items-center gap-2">
              <input type="radio" name={`${timeId}-when`} className="accent-blue-600" checked={when === "later"} onChange={() => setWhen("later")} />
              В заданное время
            </label>
          </div>
          {when === "later" && (
            <div className="space-y-2">
              <label htmlFor={timeId} className="block text-sm">Дата и время смены</label>
              <input id={timeId} type="datetime-local" value={at} onInput={(e) => { setAt(e.currentTarget.value); setTimeError(null); }} className="input-base w-auto max-w-full py-1.5" required aria-invalid={!!dateError} aria-describedby={`${timeId}-hint${dateError ? ` ${timeId}-error` : ""}`} />
              <p id={`${timeId}-hint`} className="text-sm text-muted-foreground">Укажите будущее время. Часовой пояс устройства — {timeZone}.</p>
              {dateError && <div id={`${timeId}-error`}><ErrorText>{dateError}</ErrorText></div>}
              <input value={comment} onChange={(e) => setComment(e.target.value)} aria-label="Комментарий к смене" placeholder="Комментарий, например «Новогодние обои»" className="input-base" maxLength={500} />
            </div>
          )}
        </section>
      </div>
    </Modal>
  );
}

function WallpaperChoice({ label, catalog, value, expanded, onToggle, onChange }: {
  label: string;
  catalog: ReturnType<typeof useWallpapers>;
  value: Choice;
  expanded: boolean;
  onToggle: () => void;
  onChange: (choice: Choice) => void;
}) {
  const pickerId = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const selectedWallpaper: Wallpaper | undefined = value.mode === "set" ? catalog.data?.find((w) => w.id === value.id) : undefined;
  const option = (mode: "keep" | "clear", text: string) => (
    <button
      type="button"
      onClick={() => onChange({ mode })}
      className="btn-ghost btn-sm"
      aria-pressed={value.mode === mode}
    >
      {text}
    </button>
  );
  return (
    <section className="py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-3">
          {selectedWallpaper && <img src={`data:image/jpeg;base64,${selectedWallpaper.thumbnail_base64}`} alt="" className="h-8 w-14 rounded object-cover" />}
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-foreground">{label}</h3>
            <p className="break-words text-sm text-muted-foreground">{selectedWallpaper?.name ?? (value.mode === "keep" ? "Без изменений" : value.mode === "clear" ? "Снять назначение" : "Изображение недоступно")}</p>
          </div>
        </div>
        <Button ref={trigger} type="button" size="sm" variant="secondary" aria-expanded={expanded} aria-controls={pickerId} aria-label={`Изменить обои — ${label}`} onClick={onToggle}>
          {expanded ? "Свернуть выбор" : "Изменить обои"}
        </Button>
      </div>
      {value.mode === "clear" && (
        <p className="mb-2 text-xs text-subtle">ПК вернутся к обоям своей группы, а если их нет — к обоям из образа Windows.</p>
      )}
      <div id={pickerId} hidden={!expanded} className="mt-2 space-y-2">
        {expanded && <>
          <div className="flex flex-wrap gap-2">{option("keep", "Не менять")}{option("clear", "Снять назначение")}</div>
          {catalog.isLoading ? <p className="text-sm text-muted-foreground">Загружаем изображения…</p> : catalog.isError ? (
            <div className="flex flex-wrap items-center gap-2">
              <ErrorText>Не удалось загрузить каталог.</ErrorText>
              <Button type="button" size="sm" variant="secondary" loading={catalog.isFetching} onClick={() => catalog.refetch()}>Повторить</Button>
            </div>
          ) : !catalog.data?.length ? (
            <p className="flex items-center gap-2 text-sm text-subtle">
              <ImageOff className="h-4 w-4" />
              Каталог пуст — загрузите изображения на странице «Обои»
            </p>
          ) : (
            <div className="grid max-h-56 grid-cols-3 gap-2 overflow-y-auto sm:grid-cols-4">
              {catalog.data.map((w) => {
                const selected = value.mode === "set" && value.id === w.id;
                return (
                  <button
                    key={w.id}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => { onChange({ mode: "set", id: w.id }); onToggle(); trigger.current?.focus(); }}
                    className={`group relative overflow-hidden rounded-lg border text-left ${selected ? "border-blue-500 ring-2 ring-blue-500/40" : "border-border hover:border-blue-500/50"}`}
                    title={`${w.name} · ${w.width}×${w.height}`}
                  >
                    <img src={`data:image/jpeg;base64,${w.thumbnail_base64}`} alt="" className="aspect-video w-full object-cover" />
                    <span className="block truncate px-1.5 py-1 text-xs text-foreground">{w.name}</span>
                    {selected && (
                      <span className="absolute right-1 top-1 rounded-full bg-blue-600 p-0.5 text-white">
                        <Check className="h-3 w-3" />
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </>}
      </div>
    </section>
  );
}
