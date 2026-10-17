import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Keyboard, Monitor, Mouse } from "lucide-react";
import type { HardwareEvent, Host, Peripheral } from "../api/types";
import { useHardwareEvents } from "../api/queries";
import { Empty, Loading } from "./ui/States";
import { formatDateTime, relativeTime } from "../lib/format";
import { formatDiskSize } from "../lib/hardware";
import {
  CATEGORY_LABELS,
  cleanName,
  connectionLabel,
  keyboards,
  memoryTitle,
  mice,
  monitorTitle,
  presence,
  PresenceState,
  pendingText,
} from "../lib/devices";

const PRESENCE_COLORS: Record<PresenceState, string> = {
  ok: "text-emerald-600 dark:text-emerald-400",
  pending: "text-amber-600 dark:text-amber-400",
  missing: "text-rose-600 dark:text-rose-400",
  unknown: "text-subtle",
};

const PRESENCE_TEXT: Record<PresenceState, string> = {
  ok: "на месте",
  pending: "не видна меньше 30 минут",
  missing: "не подключена",
  unknown: "нет данных",
};

/** Ячейка реестра: клавиатура, мышь и монитор — на месте, пропали недавно или отсутствуют */
export function PeripheralCell({ host }: { host: Host }) {
  if (!host.hw_components) return <span className="text-xs text-muted-foreground">—</span>;
  const items: [string, ReactNode, PresenceState][] = [
    ["Клавиатура", <Keyboard key="k" className="h-3.5 w-3.5" />, presence(host, "keyboard")],
    ["Мышь", <Mouse key="m" className="h-3.5 w-3.5" />, presence(host, "mouse")],
    ["Монитор", <Monitor key="d" className="h-3.5 w-3.5" />, presence(host, "monitor")],
  ];
  return (
    <span className="flex items-center gap-1.5" title={items.map(([label, , state]) => `${label}: ${PRESENCE_TEXT[state]}`).join("\n")}>
      {items.map(([label, icon, state]) => (
        <span key={label} className={PRESENCE_COLORS[state]} aria-label={`${label}: ${PRESENCE_TEXT[state]}`}>
          {icon}
        </span>
      ))}
    </span>
  );
}

function Group({ title, children, empty }: { title: string; children: ReactNode; empty?: string }) {
  return (
    <section>
      <h3 className="mb-2 text-sm font-semibold text-foreground">{title}</h3>
      {children ?? <p className="text-sm text-subtle">{empty}</p>}
    </section>
  );
}

function Rows({ rows }: { rows: { key: string; title: ReactNode; meta?: ReactNode; side?: ReactNode }[] }) {
  if (rows.length === 0) return null;
  return (
    <ul className="divide-y divide-border rounded-lg border border-border">
      {rows.map((r) => (
        <li key={r.key} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 px-3 py-2 text-sm">
          <span className="min-w-0 flex-1">
            <span className="text-foreground">{r.title}</span>
            {r.meta && <span className="block truncate text-xs text-muted-foreground">{r.meta}</span>}
          </span>
          {r.side && <span className="text-xs tabular-nums text-muted-foreground">{r.side}</span>}
        </li>
      ))}
    </ul>
  );
}

const Missing = ({ children }: { children: ReactNode }) => <span className="text-rose-600 dark:text-rose-400">{children}</span>;

const serial = (value: string | null | undefined) => (value ? <span className="font-mono">с/н {value}</span> : null);
const join = (...parts: ReactNode[]) => {
  const present = parts.filter((p) => p !== null && p !== undefined && p !== "" && p !== false);
  return present.length ? present.reduce<ReactNode[]>((acc, p, i) => (i ? [...acc, " · ", p] : [p]), []) : null;
};

function peripheralRows(devices: Peripheral[], prefix: string) {
  return devices.map((d, i) => ({
    key: `${prefix}${i}`,
    title: d.name ?? "Без имени",
    meta: join(d.vid ? <span className="font-mono">{d.vid}:{d.pid}</span> : null, serial(d.serial)),
  }));
}

/** Вкладка карточки «Оборудование»: состав рабочего места и журнал изменений */
export function WorkplaceTab({ host }: { host: Host }) {
  const c = host.hw_components;
  const pending = host.hw_pending_devices ?? [];
  return (
    <div className="space-y-6">
      {!c ? (
        <p className="text-sm text-subtle">
          {host.has_agent ? "Агент ещё не прислал состав рабочего места — его собирает агент с версии 2026.10.17" : "Состав рабочего места собирает агент"}
        </p>
      ) : (
        <>
          {pending.length > 0 && (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-sm">
              {pending.map((p) => (
                <p key={`${p.category}${p.since}${pendingText(p)}`} className="text-amber-700 dark:text-amber-300">
                  {pendingText(p)}: {p.missing ? "не видно" : "подключено"} с {formatDateTime(p.since)}. Изменение попадёт в журнал, если продержится 30 минут.
                </p>
              ))}
            </div>
          )}

          <Group title="Рабочее место">
            <Rows
              rows={[
                ...(keyboards(host).length
                  ? peripheralRows(keyboards(host), "k").map((r) => ({ ...r, side: "клавиатура" }))
                  : [{ key: "nok", title: <Missing>Клавиатура не подключена</Missing> }]),
                ...(mice(host).length
                  ? peripheralRows(mice(host), "m").map((r) => ({ ...r, side: "мышь" }))
                  : [{ key: "nom", title: <Missing>Мышь не подключена</Missing> }]),
                ...(c.monitors.length
                  ? c.monitors.map((m, i) => ({
                      key: `d${i}`,
                      title: monitorTitle(m),
                      meta: join(connectionLabel(m.connection), m.year ? `${m.year} г.` : null, serial(m.serial_number)),
                      side: "монитор",
                    }))
                  : [{ key: "nod", title: <Missing>Монитор не подключён или выключен</Missing> }]),
              ]}
            />
          </Group>

          <Group title="Системный блок">
            <Rows
              rows={[
                ...(c.baseboard
                  ? [{ key: "board", title: [c.baseboard.manufacturer, c.baseboard.product].filter(Boolean).join(" "), meta: join(c.bios_version ? `BIOS ${c.bios_version}` : null, serial(c.baseboard.serial_number)), side: "плата" }]
                  : []),
                ...c.gpus.map((g, i) => ({ key: `g${i}`, title: cleanName(g.name), meta: g.driver_version ? `драйвер ${g.driver_version}` : null, side: "видео" })),
                ...c.memory_modules.map((m, i) => ({
                  key: `r${i}`,
                  title: memoryTitle(m),
                  meta: join(m.slot, m.speed_mhz ? `${m.speed_mhz} МГц` : null, serial(m.serial_number)),
                  side: "память",
                })),
                ...c.physical_disks.map((d, i) => ({
                  key: `s${i}`,
                  title: d.model ?? "Диск",
                  meta: join(d.bus_type, d.size_bytes ? formatDiskSize(d.size_bytes) : null, serial(d.serial_number)),
                  side: "диск",
                })),
              ]}
            />
          </Group>

          {c.usb_devices.length > 0 && (
            <Group title="Прочие USB-устройства">
              <Rows
                rows={peripheralRows(
                  c.usb_devices.filter((u) => !c.input_devices.some((d) => d.vid === u.vid && d.pid === u.pid)),
                  "u",
                )}
              />
            </Group>
          )}
        </>
      )}

      <Group title="Журнал изменений">
        <HardwareLog hostId={host.id} />
      </Group>
    </div>
  );
}

const ACTION_COLORS: Record<HardwareEvent["action"], string> = {
  added: "bg-emerald-500",
  removed: "bg-rose-500",
  changed: "bg-amber-500",
};

function HardwareLog({ hostId }: { hostId: string }) {
  const { data, isLoading } = useHardwareEvents({ host_id: hostId, days: 3650, limit: 200 });
  if (isLoading) return <Loading />;
  if (!data?.length) return <Empty>Изменений оборудования не было</Empty>;
  return <EventList events={data} />;
}

/** Записи журнала оборудования; withHost — для общего журнала на «Обзоре» */
export function EventList({ events, withHost = false }: { events: HardwareEvent[]; withHost?: boolean }) {
  return (
    <ul className="divide-y divide-border">
      {events.map((e) => (
        <li key={e.id} className="flex items-start gap-3 py-2 text-sm">
          <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${ACTION_COLORS[e.action]}`} />
          <span className="min-w-0 flex-1">
            <span className="text-foreground">{e.summary}</span>
            <span className="block text-xs text-muted-foreground">
              {withHost && (
                <>
                  <Link to={`/hosts?host=${e.host_id}`} className="font-medium text-blue-600 hover:underline dark:text-blue-400">
                    {e.hostname ?? "ПК"}
                  </Link>
                  {" · "}
                </>
              )}
              {CATEGORY_LABELS[e.category] ?? e.category}
            </span>
          </span>
          <span className="shrink-0 text-xs text-muted-foreground" title={formatDateTime(e.created_at)}>
            {relativeTime(e.created_at)}
          </span>
        </li>
      ))}
    </ul>
  );
}
