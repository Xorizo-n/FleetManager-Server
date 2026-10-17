import type { DeviceCategory, Host, HwComponents, PendingDevice, Peripheral } from "../api/types";
import { formatRam } from "./format";

// Состав рабочего места: агент присылает его в каждом heartbeat, изменения ведёт сервер
// (backend/services/workplace_devices.py) — периферия подтверждается через 30 минут.

export const CATEGORY_LABELS: Record<DeviceCategory, string> = {
  system: "Система",
  baseboard: "Материнская плата",
  bios: "BIOS",
  memory: "Память",
  disk: "Диск",
  gpu: "Видеокарта",
  monitor: "Монитор",
  keyboard: "Клавиатура",
  mouse: "Мышь",
  usb: "USB",
};

/** VideoOutputTechnology монитора */
export function connectionLabel(value: number | null | undefined): string | null {
  if (value === null || value === undefined) return null;
  if (value === 2147483648 || value === -2147483648) return "встроенный";
  return ({ 0: "VGA", 4: "DVI", 5: "HDMI", 6: "LVDS", 10: "DisplayPort", 11: "DisplayPort", 16: "USB-C" } as Record<number, string>)[value] ?? null;
}

/** «Intel(R) UHD Graphics 770» -> «Intel UHD Graphics 770» */
export const cleanName = (name: string | null | undefined) => (name ?? "").replace(/\((R|TM|tm|r)\)/g, "").replace(/\s+/g, " ").trim();

export const peripheralTitle = (d: Peripheral) => `${d.name ?? "Без имени"}${d.vid ? ` (${d.vid}:${d.pid})` : ""}`;

export const monitorTitle = (m: HwComponents["monitors"][number]) => [m.manufacturer, m.model ?? m.product_code].filter(Boolean).join(" ") || "Монитор";

export function memoryTitle(m: HwComponents["memory_modules"][number]) {
  return [m.manufacturer && !/^0x/i.test(m.manufacturer) ? m.manufacturer : null, m.part_number, m.capacity_bytes ? formatRam(m.capacity_bytes) : null]
    .filter(Boolean)
    .join(" ") || "Модуль памяти";
}

export const keyboards = (h: Host) => h.hw_components?.input_devices.filter((d) => d.kind === "keyboard") ?? [];
export const mice = (h: Host) => h.hw_components?.input_devices.filter((d) => d.kind === "mouse") ?? [];

const pendingMissing = (h: Host, category: DeviceCategory) => (h.hw_pending_devices ?? []).filter((p) => p.missing && p.category === category);

export type PresenceState = "ok" | "pending" | "missing" | "unknown";

/**
 * Клавиатура, мышь, монитор: ok — на месте; pending — одно из устройств пропало меньше 30 минут назад;
 * missing — нет ни одного; unknown — агент не присылает состав (старая версия).
 */
export function presence(h: Host, category: "keyboard" | "mouse" | "monitor"): PresenceState {
  const c = h.hw_components;
  if (!c) return "unknown";
  const count = category === "keyboard" ? keyboards(h).length : category === "mouse" ? mice(h).length : c.monitors.length;
  if (count === 0) return "missing";
  return pendingMissing(h, category).length ? "pending" : "ok";
}

export function pendingText(p: PendingDevice): string {
  const item = p.item as Record<string, string | null>;
  const name = item.model ?? item.name ?? item.product_code ?? "";
  return `${CATEGORY_LABELS[p.category]}${name ? ` «${name}»` : ""}`;
}
