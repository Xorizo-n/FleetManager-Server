import type { Host, HostDisk, NetworkAdapter } from "../api/types";

/** Заполненность диска, % — от 90 красная, от 80 жёлтая */
export const DISK_WARN_PERCENT = 80;
export const DISK_CRITICAL_PERCENT = 90;

export function diskUsedPercent(disk: HostDisk): number {
  if (!disk.size_bytes) return 0;
  return Math.min(100, Math.max(0, Math.round(((disk.size_bytes - disk.free_bytes) / disk.size_bytes) * 100)));
}

/** Самый заполненный диск — по нему видно, где кончается место */
export function fullestDisk(host: Host): HostDisk | null {
  const disks = host.hw_disks ?? [];
  return disks.reduce<HostDisk | null>((worst, d) => (!worst || diskUsedPercent(d) > diskUsedPercent(worst) ? d : worst), null);
}

export function diskTone(percent: number) {
  return percent >= DISK_CRITICAL_PERCENT ? "critical" : percent >= DISK_WARN_PERCENT ? "warn" : "ok";
}

export function formatDiskSize(bytes: number): string {
  const gb = bytes / 1024 ** 3;
  if (gb >= 1024) return `${(gb / 1024).toFixed(gb >= 10 * 1024 ? 0 : 1).replace(".", ",")} ТБ`;
  return `${gb >= 10 ? Math.round(gb) : gb.toFixed(1).replace(".", ",")} ГБ`;
}

/** 1 000 000 000 -> «1 Гбит/с», 2 500 000 000 -> «2,5 Гбит/с», 576 500 000 -> «576,5 Мбит/с» */
export function formatLinkSpeed(bps: number | null | undefined): string | null {
  if (!bps) return null;
  const trim = (value: number) => String(Math.round(value * 10) / 10).replace(".", ",");
  if (bps >= 1e9) return `${trim(bps / 1e9)} Гбит/с`;
  if (bps >= 1e6) return `${trim(bps / 1e6)} Мбит/с`;
  return `${trim(bps / 1e3)} кбит/с`;
}

/** Адаптер, через который ПК пришёл на сервер (его MAC сервер хранит в hw_mac_address) */
export function primaryAdapter(host: Host): NetworkAdapter | null {
  const adapters = host.hw_network_adapters ?? [];
  return adapters.find((a) => host.hw_mac_address && a.mac_address === host.hw_mac_address) ?? null;
}

/** Проводной адаптер медленнее гигабита — обычно плохой кабель, патч-корд или порт */
export function isSlowWiredLink(adapter: NetworkAdapter | null): boolean {
  return !!adapter?.link_speed_bps && adapter.media_type === "802.3" && adapter.link_speed_bps < 1e9;
}
