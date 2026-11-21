import { useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Image as ImageIcon, Trash2, Upload, X } from "lucide-react";
import { apiClient } from "../api/client";
import { useCanEdit, useFleet, useWallpaperAssignments, useWallpaperSchedules, useWallpapers } from "../api/queries";
import type { Wallpaper, WallpaperAssignment, WallpaperKind, WallpaperSchedule } from "../api/types";
import PageHeader from "../components/ui/PageHeader";
import Card from "../components/ui/Card";
import Button from "../components/ui/Button";
import Badge from "../components/ui/Badge";
import { Empty, Loading } from "../components/ui/States";
import { useToast } from "../components/ui/Toast";
import WallpaperAssignDialog from "../components/WallpaperAssignDialog";
import WallpaperAssignments from "../components/WallpaperAssignments";
import WallpaperThumb, { useThumbnails } from "../components/WallpaperThumb";
import { apiError, formatDateTime, formatSize, pcCount, plural } from "../lib/format";
import { currentDistribution, KIND_LABELS, KINDS } from "../lib/wallpapers";

const SCHEDULE_STATUS: Record<WallpaperSchedule["status"], { label: string; tone: "info" | "success" | "neutral" | "danger" }> = {
  pending: { label: "ждёт", tone: "info" },
  applied: { label: "выполнена", tone: "success" },
  cancelled: { label: "отменена", tone: "neutral" },
  failed: { label: "ошибка", tone: "danger" },
};

export default function Wallpapers() {
  const canEdit = useCanEdit();
  const queryClient = useQueryClient();
  const toast = useToast();
  const { hosts, hostById, tree, isLoading: fleetLoading } = useFleet();
  const catalog = useWallpapers();
  const assignments = useWallpaperAssignments();
  const schedules = useWallpaperSchedules();
  const thumbnails = useThumbnails();
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [assignFor, setAssignFor] = useState<{ wallpaperId?: string } | null>(null);

  const byWallpaper = useMemo(() => {
    const map = new Map<string, WallpaperAssignment[]>();
    for (const a of assignments.data ?? []) map.set(a.wallpaper_id, [...(map.get(a.wallpaper_id) ?? []), a]);
    return map;
  }, [assignments.data]);
  const showing = useMemo(() => {
    const map = new Map<string, number>();
    for (const h of hosts) for (const kind of KINDS) {
      const sha = h.wallpaper_state?.[kind]?.sha256;
      if (sha) map.set(sha, (map.get(sha) ?? 0) + 1);
    }
    return map;
  }, [hosts]);
  const reporting = hosts.filter((h) => h.wallpaper_state).length;

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["wallpapers"] });

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setUploading(true);
    const failed: string[] = [];
    let done = 0;
    for (const file of Array.from(files)) {
      const form = new FormData();
      form.append("file", file);
      try {
        await apiClient.post("/wallpapers", form);
        done += 1;
      } catch (err) {
        failed.push(`${file.name}: ${apiError(err, "не загружен")}`);
      }
    }
    setUploading(false);
    if (fileRef.current) fileRef.current.value = "";
    refresh();
    if (done) toast({ tone: "success", message: `Загружено: ${plural(done, "изображение", "изображения", "изображений")}` });
    if (failed.length) toast({ tone: "error", message: failed.join("; ") });
  }

  async function remove(w: Wallpaper) {
    if (!window.confirm(`Удалить «${w.name}» из каталога?`)) return;
    try {
      await apiClient.delete(`/wallpapers/${w.id}`);
      refresh();
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось удалить") });
    }
  }

  async function openFull(w: Wallpaper) {
    try {
      const { data } = await apiClient.get<Blob>(`/wallpapers/${w.id}/image`, { responseType: "blob" });
      window.open(URL.createObjectURL(data), "_blank", "noopener");
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось открыть изображение") });
    }
  }

  async function cancel(s: WallpaperSchedule) {
    try {
      await apiClient.delete(`/wallpapers/schedules/${s.id}`);
      refresh();
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось отменить") });
    }
  }

  const wallpaperById = useMemo(() => new Map((catalog.data ?? []).map((w) => [w.id, w])), [catalog.data]);
  const pending = (schedules.data ?? []).filter((s) => s.status === "pending");
  const history = (schedules.data ?? []).filter((s) => s.status !== "pending").slice(0, 10);

  return (
    <div className="animate-fade-in space-y-6">
      <PageHeader
        title="Обои"
        description={`Рабочий стол и экран блокировки. Обои сообщают ${pcCount(reporting)} из ${hosts.length} — агент с версии 2026.10.18`}
        actions={
          canEdit && (
            <>
              <Button size="sm" variant="secondary" onClick={() => fileRef.current?.click()} loading={uploading}>
                <Upload className="h-3.5 w-3.5" />
                Загрузить
              </Button>
              <Button size="sm" onClick={() => setAssignFor({})} disabled={!catalog.data?.length}>
                <ImageIcon className="h-3.5 w-3.5" />
                Назначить обои…
              </Button>
              <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/bmp" multiple className="hidden" onChange={(e) => upload(e.target.files)} />
            </>
          )
        }
      />

      <Card title="Сейчас на ПК">
        {reporting === 0 ? (
          <p className="py-4 text-sm text-subtle">Пока ни один агент не сообщил обои — они появятся после обновления агента до 2026.10.18</p>
        ) : (
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            {KINDS.map((kind) => (
              <div key={kind}>
                <h3 className="mb-2 text-sm font-semibold text-foreground">{KIND_LABELS[kind]}</h3>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                  {currentDistribution(hosts, kind, thumbnails).slice(0, 9).map((d) => (
                    <div key={d.filter} className="min-w-0">
                      <WallpaperThumb sha256={d.sha256} path={d.path || null} thumbnails={thumbnails} className="w-full" />
                      <Link to={`/hosts?wallpaper=${encodeURIComponent(d.filter)}`} className="text-xs text-blue-600 hover:underline dark:text-blue-400">
                        {pcCount(d.hostIds.length)}
                      </Link>
                      {d.variants.length > 1 && (
                        <span
                          className="text-xs text-subtle"
                          title={`Одна картинка в ${d.variants.length} файлах: на каждом ПК или у каждого пользователя она сохранена заново\n${d.variants.map((v) => `${v.path} — ${pcCount(v.count)}`).join("\n")}`}
                        >
                          {" "}· {plural(d.variants.length, "вариант", "варианта", "вариантов")} файла
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title={`Каталог${catalog.data ? ` · ${catalog.data.length}` : ""}`}>
        {catalog.isLoading ? (
          <Loading />
        ) : !catalog.data?.length ? (
          <Empty>Каталог пуст. Загрузите JPEG, PNG или BMP до 30 МБ — лучше в разрешении мониторов (1920×1080 и выше)</Empty>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {catalog.data.map((w) => {
              const used = byWallpaper.get(w.id) ?? [];
              const groups = used.filter((a) => a.group_id).length;
              const own = used.length - groups;
              return (
                <div key={w.id} className="min-w-0 border-b border-border pb-3">
                  <button onClick={() => openFull(w)} className="block w-full overflow-hidden rounded-md" title="Открыть в полном размере">
                    <img src={`data:image/jpeg;base64,${w.thumbnail_base64}`} alt="" className="aspect-video w-full object-cover" />
                  </button>
                  <div className="space-y-1 pt-2">
                    <div className="truncate text-sm font-medium text-foreground" title={w.original_name ?? undefined}>{w.name}</div>
                    <div className="text-xs text-muted-foreground">
                      {w.width}×{w.height} · {formatSize(w.size_bytes)}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {used.length ? `Назначено: ${[groups && plural(groups, "группа", "группы", "групп"), own && pcCount(own)].filter(Boolean).join(", ")}` : "Не назначено"}
                      {showing.get(w.sha256) ? ` · стоит на ${pcCount(showing.get(w.sha256)!)}` : ""}
                    </div>
                    {canEdit && (
                      <div className="flex gap-2 pt-1">
                        <Button size="sm" variant="secondary" onClick={() => setAssignFor({ wallpaperId: w.id })}>Назначить…</Button>
                        <button className="btn-ghost btn-sm ml-auto text-rose-600 dark:text-rose-400" onClick={() => remove(w)} aria-label={`Удалить ${w.name}`} title="Удалить из каталога">
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      <WallpaperAssignments tree={tree} hostById={hostById} catalog={wallpaperById} canEdit={canEdit} fleetLoading={fleetLoading} />

      <Card title="Смена по расписанию">
        {!pending.length && !history.length ? (
          <p className="py-4 text-sm text-subtle">Запланированных смен нет. Чтобы сменить обои в заданное время, выберите «В заданное время» при назначении.</p>
        ) : (
          <ul className="divide-y divide-border">
            {[...pending.sort((a, b) => a.apply_at.localeCompare(b.apply_at)), ...history].map((s) => (
              <li key={s.id} className="flex flex-wrap items-center gap-3 py-2.5 text-sm">
                <CalendarClock className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span className="w-36 shrink-0 tabular-nums text-foreground">{formatDateTime(s.apply_at)}</span>
                <span className="min-w-0 flex-1 text-muted-foreground">
                  {[s.group_ids.length && s.group_ids.map((g) => tree.pathOf(g)).join(", "), s.host_ids.length && pcCount(s.host_ids.length)].filter(Boolean).join(" + ")}
                  {" — "}
                  {KINDS.map((kind) => describeChange(kind, s[kind], wallpaperById)).filter(Boolean).join("; ")}
                  {s.comment && <span className="text-subtle"> · {s.comment}</span>}
                  {s.result && s.status !== "pending" && <span className="text-subtle"> · {s.result}</span>}
                </span>
                <span className="text-xs text-subtle">{s.created_by_name}</span>
                <Badge status={s.status} tone={SCHEDULE_STATUS[s.status].tone} staticIndicator>{SCHEDULE_STATUS[s.status].label}</Badge>
                {canEdit && s.status === "pending" && (
                  <button className="btn-ghost btn-sm" onClick={() => cancel(s)} title="Отменить смену" aria-label="Отменить смену">
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>

      {assignFor && <WallpaperAssignDialog initialWallpaperId={assignFor.wallpaperId} onClose={() => setAssignFor(null)} />}
    </div>
  );
}
function describeChange(kind: WallpaperKind, value: string | null, byId: Map<string, Wallpaper>): string | null {
  if (!value) return null;
  const label = KIND_LABELS[kind].toLowerCase();
  return value === "clear" ? `${label}: снять назначение` : `${label}: ${byId.get(value)?.name ?? "удалённое изображение"}`;
}
