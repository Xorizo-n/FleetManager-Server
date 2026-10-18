import type { Host, ObservedWallpaper, Wallpaper, WallpaperAssignment, WallpaperKind } from "../api/types";
import type { GroupTree } from "./groupTree";

// Те же правила, что на сервере (backend/services/wallpapers.py): у ПК действует своё назначение,
// иначе ближайшей группы вверх по дереву; нет нигде — обоями сервер не управляет.

export const KINDS: WallpaperKind[] = ["desktop", "lock_screen"];
export const KIND_LABELS: Record<WallpaperKind, string> = { desktop: "Рабочий стол", lock_screen: "Экран блокировки" };

export interface AssignmentIndex {
  byHost: Map<string, Partial<Record<WallpaperKind, WallpaperAssignment>>>;
  byGroup: Map<string, Partial<Record<WallpaperKind, WallpaperAssignment>>>;
}

export function indexAssignments(assignments: WallpaperAssignment[] = []): AssignmentIndex {
  const byHost = new Map<string, Partial<Record<WallpaperKind, WallpaperAssignment>>>();
  const byGroup = new Map<string, Partial<Record<WallpaperKind, WallpaperAssignment>>>();
  for (const a of assignments) {
    const map = a.host_id ? byHost : byGroup;
    const key = (a.host_id ?? a.group_id)!;
    map.set(key, { ...map.get(key), [a.kind]: a });
  }
  return { byHost, byGroup };
}

/** Назначение, действующее для ПК, и откуда оно: свой ПК или группа (её путь) */
export function effectiveAssignment(host: Host, kind: WallpaperKind, index: AssignmentIndex, tree: GroupTree) {
  const own = index.byHost.get(host.id)?.[kind];
  if (own) return { assignment: own, from: null as string | null };
  let groupId = host.group_id;
  const seen = new Set<string>();
  while (groupId && !seen.has(groupId)) {
    seen.add(groupId);
    const found = index.byGroup.get(groupId)?.[kind];
    if (found) return { assignment: found, from: tree.pathOf(groupId) };
    groupId = tree.byId.get(groupId)?.group?.parent_id ?? null;
  }
  return null;
}

export type WallpaperStatus = "applied" | "pending" | "error" | "unmanaged" | "unknown";

/**
 * applied — на ПК стоит назначенное; pending — назначено, но агент ещё не поставил (ПК выключен
 * или не прошёл heartbeat); error — агент сообщил ошибку; unmanaged — ничего не назначено;
 * unknown — агент не присылает обои (старая версия).
 */
export function wallpaperStatus(host: Host, kind: WallpaperKind, wallpaper: Wallpaper | undefined | null): WallpaperStatus {
  const state = host.wallpaper_state;
  if (!wallpaper) return "unmanaged";
  if (!state) return "unknown";
  if (state[kind]?.sha256 === wallpaper.sha256) return "applied";
  return state.error ? "error" : "pending";
}

export const STATUS_LABELS: Record<WallpaperStatus, string> = {
  applied: "стоит",
  pending: "ещё не применены",
  error: "ошибка",
  unmanaged: "не назначены",
  unknown: "агент не сообщает",
};

/** Миниатюры по sha256: каталог и обои не из каталога, которые прислали агенты */
export function thumbnailIndex(catalog: Wallpaper[] = [], observed: ObservedWallpaper[] = []) {
  const map = new Map<string, { src: string; name: string; phash: string | null; wallpaper?: Wallpaper }>();
  for (const o of observed) map.set(o.sha256, { src: `data:image/jpeg;base64,${o.thumbnail_base64}`, name: fileName(o.path) ?? "Не из каталога", phash: o.phash });
  for (const w of catalog) map.set(w.sha256, { src: `data:image/jpeg;base64,${w.thumbnail_base64}`, name: w.name, phash: w.phash, wallpaper: w });
  return map;
}

/**
 * Варианты одной картинки, сохранённые заново (другое сжатие или разрешение), отличаются по SHA-256,
 * но не по виду: dHash расходится на 1–7 бит из 64, у разных обоев — на 21 и больше.
 * Так выглядит urfu-desktop.jpg, который создаётся в профиле каждого пользователя под его экран.
 */
export const SAME_PICTURE_BITS = 10;

export function phashDistance(a: string, b: string): number {
  let bits = 0;
  for (let i = 0; i < 16; i += 8) {
    let x = (parseInt(a.slice(i, i + 8), 16) ^ parseInt(b.slice(i, i + 8), 16)) >>> 0;
    while (x) {
      bits += x & 1;
      x >>>= 1;
    }
  }
  return bits;
}

export const fileName = (path: string | null | undefined) => path?.split(/[\\/]/).pop() || null;

export interface WallpaperGroup {
  /** Вариант, который стоит на большинстве ПК группы, — его миниатюра и показывается */
  sha256: string | null;
  path: string;
  hostIds: string[];
  /** Все варианты файла одной картинки */
  variants: { sha256: string | null; path: string; count: number }[];
  /** Значение фильтра реестра «wallpaper»: хэши через запятую, «path:…» или «none» */
  filter: string;
}

/** Сколько ПК показывают каждую картинку — «что сейчас стоит». Варианты одной картинки — одна плитка. */
export function currentDistribution(hosts: Host[], kind: WallpaperKind, thumbnails?: ReturnType<typeof thumbnailIndex>): WallpaperGroup[] {
  const exact = new Map<string, { sha256: string | null; path: string; hostIds: string[] }>();
  for (const h of hosts) {
    if (!h.wallpaper_state) continue;
    const current = h.wallpaper_state[kind];
    const key = current?.sha256 ?? (current ? `path:${current.path.toLowerCase()}` : "none");
    const entry = exact.get(key) ?? { sha256: current?.sha256 ?? null, path: current?.path ?? "", hostIds: [] };
    entry.hostIds.push(h.id);
    exact.set(key, entry);
  }
  const groups: (WallpaperGroup & { phash: string | null })[] = [];
  for (const entry of [...exact.values()].sort((a, b) => b.hostIds.length - a.hostIds.length)) {
    const phash = entry.sha256 ? thumbnails?.get(entry.sha256)?.phash ?? null : null;
    const same = phash ? groups.find((g) => g.phash && phashDistance(g.phash, phash) <= SAME_PICTURE_BITS) : undefined;
    const variant = { sha256: entry.sha256, path: entry.path, count: entry.hostIds.length };
    if (same) {
      same.hostIds.push(...entry.hostIds);
      same.variants.push(variant);
      same.filter = same.variants.map((v) => v.sha256).join(",");
      continue;
    }
    groups.push({
      sha256: entry.sha256, path: entry.path, hostIds: [...entry.hostIds], variants: [variant], phash,
      filter: entry.sha256 ?? (entry.path ? `path:${entry.path}` : "none"),
    });
  }
  return groups.sort((a, b) => b.hostIds.length - a.hostIds.length);
}
