import { useEffect, useState } from "react";
import { Cpu, HardDrive, MemoryStick, Search } from "lucide-react";
import { apiClient } from "../api/client";
import Card from "../components/ui/Card";

interface HostHardware {
  id: string;
  hostname: string | null;
  ip_address: string | null;
  status: "online" | "offline" | "unknown";
  hw_manufacturer: string | null;
  hw_model: string | null;
  hw_serial_number: string | null;
  hw_os_caption: string | null;
  hw_processor: string | null;
  hw_total_memory_bytes: number | null;
}

function formatRam(bytes: number | null): string {
  if (!bytes) return "—";
  const gb = bytes / (1024 ** 3);
  return gb >= 1 ? `${Math.round(gb)} ГБ` : `${Math.round(bytes / (1024 ** 2))} МБ`;
}

function StatusDot({ status }: { status: string }) {
  const cls =
    status === "online"
      ? "bg-emerald-500"
      : status === "offline"
      ? "bg-rose-500"
      : "bg-slate-400";
  return <span className={`inline-block h-2 w-2 rounded-full ${cls}`} />;
}

export default function Hardware() {
  const [rows, setRows] = useState<HostHardware[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    const params = search ? { search } : {};
    apiClient
      .get("/hardware", { params })
      .then((r) => setRows(r.data))
      .finally(() => setLoading(false));
  }, [search]);

  const withHardware = rows.filter((r) => r.hw_processor || r.hw_model);
  const totalRam = withHardware.reduce((s, r) => s + (r.hw_total_memory_bytes ?? 0), 0);
  const uniqueModels = new Set(rows.map((r) => r.hw_model).filter(Boolean)).size;

  return (
    <div className="animate-fade-in space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Железо ПК</h1>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
        <Card>
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-muted-foreground">Агентов с данными</span>
            <HardDrive className="h-4 w-4 text-muted-foreground" />
          </div>
          <p className="mt-2 text-3xl font-bold tabular-nums">{withHardware.length}</p>
        </Card>
        <Card>
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-muted-foreground">Суммарная RAM</span>
            <MemoryStick className="h-4 w-4 text-muted-foreground" />
          </div>
          <p className="mt-2 text-3xl font-bold tabular-nums">{formatRam(totalRam)}</p>
        </Card>
        <Card>
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-muted-foreground">Моделей ПК</span>
            <Cpu className="h-4 w-4 text-muted-foreground" />
          </div>
          <p className="mt-2 text-3xl font-bold tabular-nums">{uniqueModels}</p>
        </Card>
      </div>

      <Card>
        <div className="mb-4 flex items-center gap-2">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground pointer-events-none" />
            <input
              type="text"
              aria-label="Поиск по оборудованию"
              placeholder="Поиск по имени, производителю, модели, процессору..."
              className="input-base pl-8 w-full"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <span className="text-sm text-muted-foreground">{rows.length} хост(ов)</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
                <th className="pb-2 pr-4">Хост</th>
                <th className="pb-2 pr-4">Производитель / Модель</th>
                <th className="pb-2 pr-4">Процессор</th>
                <th className="pb-2 pr-4">RAM</th>
                <th className="pb-2 pr-4">ОС</th>
                <th className="pb-2 pr-4">Накопитель</th>
                <th className="pb-2">Статус</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {loading && (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-muted-foreground">
                    Загрузка...
                  </td>
                </tr>
              )}
              {!loading && rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-muted-foreground">
                    Нет агентов с данными об оборудовании
                  </td>
                </tr>
              )}
              {rows.map((row) => (
                <tr key={row.id} className="group hover:bg-muted/40 transition-colors">
                  <td className="py-3 pr-4 font-medium">
                    <div>{row.hostname ?? <span className="text-muted-foreground">—</span>}</div>
                    {row.ip_address && (
                      <div className="text-xs text-muted-foreground font-mono">{row.ip_address}</div>
                    )}
                  </td>
                  <td className="py-3 pr-4">
                    {row.hw_manufacturer || row.hw_model ? (
                      <>
                        <div>{row.hw_manufacturer ?? ""}</div>
                        <div className="text-xs text-muted-foreground">{row.hw_model ?? ""}</div>
                      </>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </td>
                  <td className="py-3 pr-4 max-w-[240px]">
                    <span className="line-clamp-2 leading-tight" title={row.hw_processor ?? ""}>
                      {row.hw_processor ?? <span className="text-muted-foreground">—</span>}
                    </span>
                  </td>
                  <td className="py-3 pr-4 tabular-nums whitespace-nowrap">
                    {formatRam(row.hw_total_memory_bytes)}
                  </td>
                  <td className="py-3 pr-4 max-w-[160px]">
                    <span className="line-clamp-1 text-xs" title={row.hw_os_caption ?? ""}>
                      {row.hw_os_caption ?? <span className="text-muted-foreground">—</span>}
                    </span>
                  </td>
                  <td className="py-3 pr-4 font-mono text-xs text-muted-foreground">
                    {row.hw_serial_number ?? "—"}
                  </td>
                  <td className="py-3">
                    <div className="flex items-center gap-1.5">
                      <StatusDot status={row.status} />
                      <span className="capitalize text-xs text-muted-foreground">{row.status}</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
