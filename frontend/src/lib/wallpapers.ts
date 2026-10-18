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
  const map = new Map<string, { src: string; name: string; wallpaper?: Wallpaper }>();
  for (const o of observed) map.set(o.sha256, { src: `data:image/jpeg;base64,${o.thumbnail_base64}`, name: fileName(o.path) ?? "Не из каталога" });
  for (const w of catalog) map.set(w.sha256, { src: `data:image/jpeg;base64,${w.thumbnail_base64}`, name: w.name, wallpaper: w });
  return map;
}

export const fileName = (path: string | null | undefined) => path?.split(/[\\/]/).pop() || null;

/** Сколько ПК показывают каждое изображение — «что сейчас стоит» */
export function currentDistribution(hosts: Host[], kind: WallpaperKind) {
  const counts = new Map<string, { sha256: string | null; path: string; hostIds: string[] }>();
  for (const h of hosts) {
    const current = h.wallpaper_state?.[kind];
    if (!h.wallpaper_state) continue;
    const key = current?.sha256 ?? (current ? `path:${current.path.toLowerCase()}` : "none");
    const entry = counts.get(key) ?? { sha256: current?.sha256 ?? null, path: current?.path ?? "", hostIds: [] };
    entry.hostIds.push(h.id);
    counts.set(key, entry);
  }
  return [...counts.values()].sort((a, b) => b.hostIds.length - a.hostIds.length);
}
