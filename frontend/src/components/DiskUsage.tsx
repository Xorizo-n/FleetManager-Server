import type { HostDisk } from "../api/types";
import { diskTone, diskUsedPercent, formatDiskSize } from "../lib/hardware";

const BAR_COLORS = { ok: "bg-emerald-500", warn: "bg-amber-500", critical: "bg-rose-500" };
const TEXT_COLORS = { ok: "text-foreground/80", warn: "text-amber-600 dark:text-amber-400", critical: "text-rose-600 dark:text-rose-400" };

function Bar({ percent, className = "h-1.5" }: { percent: number; className?: string }) {
  return (
    <div className={`w-full overflow-hidden rounded-full bg-muted ${className}`}>
      <div className={`h-full rounded-full ${BAR_COLORS[diskTone(percent)]}`} style={{ width: `${percent}%` }} />
    </div>
  );
}

export function diskSummary(disk: HostDisk) {
  return `${disk.name} — свободно ${formatDiskSize(disk.free_bytes)} из ${formatDiskSize(disk.size_bytes)} (занято ${diskUsedPercent(disk)}%)`;
}

/** Ячейка реестра: самый заполненный диск, остальные — во всплывающей подсказке */
export function DiskCell({ disk, all }: { disk: HostDisk | null; all: HostDisk[] }) {
  if (!disk) return <span className="text-muted-foreground">—</span>;
  const percent = diskUsedPercent(disk);
  return (
    <div className="min-w-0" title={all.map(diskSummary).join("\n")}>
      <div className={`flex items-baseline justify-between gap-1 text-xs tabular-nums ${TEXT_COLORS[diskTone(percent)]}`}>
        <span>{disk.name}</span>
        <span>{percent}%</span>
      </div>
      <Bar percent={percent} className="mt-0.5 h-1" />
    </div>
  );
}

/** Карточка хоста: все диски с полосой заполненности */
export function DiskList({ disks }: { disks: HostDisk[] }) {
  return (
    <ul className="space-y-3">
      {disks.map((disk) => {
        const percent = diskUsedPercent(disk);
        return (
          <li key={disk.name} className="text-sm">
            <div className="mb-1 flex flex-wrap items-baseline justify-between gap-x-3">
              <span className="text-foreground">
                <span className="font-medium">{disk.name}</span>
                {disk.label && <span className="text-muted-foreground"> {disk.label}</span>}
                {disk.file_system && <span className="text-xs text-subtle"> · {disk.file_system}</span>}
              </span>
              <span className={`text-xs tabular-nums ${TEXT_COLORS[diskTone(percent)]}`}>
                свободно {formatDiskSize(disk.free_bytes)} из {formatDiskSize(disk.size_bytes)} · занято {percent}%
              </span>
            </div>
            <Bar percent={percent} />
          </li>
        );
      })}
    </ul>
  );
}
