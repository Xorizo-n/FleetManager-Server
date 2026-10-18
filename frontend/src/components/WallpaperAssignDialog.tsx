import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Check, ImageOff } from "lucide-react";
import { apiClient } from "../api/client";
import { keys, useFleet, useWallpapers } from "../api/queries";
import type { Wallpaper, WallpaperKind } from "../api/types";
import Modal from "./ui/Modal";
import Button from "./ui/Button";
import { ErrorText } from "./ui/States";
import { useToast } from "./ui/Toast";
import HostPicker from "./HostPicker";
import { compactSelection } from "../lib/groupTree";
import { apiError, pcCount } from "../lib/format";
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
  const [choices, setChoices] = useState<Record<WallpaperKind, Choice>>({
    desktop: initialWallpaperId ? { mode: "set", id: initialWallpaperId } : { mode: "keep" },
    lock_screen: { mode: "keep" },
  });
  const [selection, setSelection] = useState<Set<string>>(() => new Set(initialHostIds));
  const [when, setWhen] = useState<"now" | "later">("now");
  const [at, setAt] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const compact = useMemo(() => compactSelection(tree, selection), [tree, selection]);
  const nothingChosen = KINDS.every((k) => choices[k].mode === "keep");
  const atDate = at ? new Date(at) : null;
  const laterInvalid = when === "later" && (!atDate || Number.isNaN(atDate.getTime()) || atDate.getTime() <= Date.now());

  const value = (choice: Choice) => (choice.mode === "set" ? choice.id : choice.mode === "clear" ? "clear" : null);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const { data } = await apiClient.post<{ changed: number; schedule_id: string | null }>("/wallpapers/assign", {
        host_ids: compact.hostIds,
        group_ids: compact.groupIds,
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
          : `Обои назначены на ${pcCount(selection.size)}: агенты поставят их в течение 5 минут, выключенные ПК — после включения`,
      });
      onClose();
    } catch (err) {
      setError(apiError(err, "Не удалось назначить обои"));
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
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={submit} loading={busy} disabled={nothingChosen || selection.size === 0 || laterInvalid}>
            {when === "now" ? `Назначить на ${pcCount(selection.size)}` : "Запланировать"}
          </Button>
          {nothingChosen && <span className="text-xs text-subtle">Выберите обои</span>}
          {!nothingChosen && selection.size === 0 && <span className="text-xs text-subtle">Выберите ПК</span>}
          <ErrorText>{error}</ErrorText>
        </div>
      }
    >
      <div className="space-y-5">
        {KINDS.map((kind) => (
          <WallpaperChoice
            key={kind}
            label={KIND_LABELS[kind]}
            catalog={catalog.data ?? []}
            value={choices[kind]}
            onChange={(choice) => setChoices((prev) => ({ ...prev, [kind]: choice }))}
          />
        ))}

        <section>
          <h3 className="mb-2 text-sm font-semibold text-foreground">На какие ПК</h3>
          <HostPicker value={selection} onChange={setSelection} height={260} />
          <p className="mt-1 text-xs text-subtle">
            Корпус, этаж или аудитория, выбранные целиком, получают назначение на всю группу — его получат и ПК, которые появятся в ней позже.
            Своё назначение у ПК важнее назначения группы.
          </p>
        </section>

        <section className="space-y-2">
          <h3 className="text-sm font-semibold text-foreground">Когда</h3>
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <label className="flex cursor-pointer items-center gap-2">
              <input type="radio" className="accent-blue-600" checked={when === "now"} onChange={() => setWhen("now")} />
              Сейчас
            </label>
            <label className="flex cursor-pointer items-center gap-2">
              <input type="radio" className="accent-blue-600" checked={when === "later"} onChange={() => setWhen("later")} />
              В заданное время
            </label>
            {when === "later" && (
              <input type="datetime-local" value={at} onChange={(e) => setAt(e.target.value)} className="input-base w-auto py-1.5" aria-label="Время смены" />
            )}
          </div>
          {when === "later" && (
            <input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Комментарий, например «Новогодние обои»" className="input-base" maxLength={500} />
          )}
        </section>
      </div>
    </Modal>
  );
}

function WallpaperChoice({ label, catalog, value, onChange }: { label: string; catalog: Wallpaper[]; value: Choice; onChange: (c: Choice) => void }) {
  const option = (mode: "keep" | "clear", text: string) => (
    <button
      type="button"
      onClick={() => onChange({ mode })}
      className={`rounded-md border px-2.5 py-1 text-xs ${value.mode === mode ? "border-blue-500 bg-blue-500/10 text-foreground" : "border-border text-muted-foreground hover:text-foreground"}`}
    >
      {text}
    </button>
  );
  return (
    <section>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="mr-2 text-sm font-semibold text-foreground">{label}</h3>
        {option("keep", "Не менять")}
        {option("clear", "Снять назначение")}
      </div>
      {value.mode === "clear" && (
        <p className="mb-2 text-xs text-subtle">ПК вернутся к обоям своей группы, а если их нет — к обоям из образа Windows.</p>
      )}
      {catalog.length === 0 ? (
        <p className="flex items-center gap-2 text-sm text-subtle">
          <ImageOff className="h-4 w-4" />
          Каталог пуст — загрузите изображения на странице «Обои»
        </p>
      ) : (
        <div className="grid max-h-56 grid-cols-3 gap-2 overflow-y-auto sm:grid-cols-4">
          {catalog.map((w) => {
            const selected = value.mode === "set" && value.id === w.id;
            return (
              <button
                key={w.id}
                type="button"
                onClick={() => onChange({ mode: "set", id: w.id })}
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
    </section>
  );
}
