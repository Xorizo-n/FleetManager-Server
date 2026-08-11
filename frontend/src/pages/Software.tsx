import { useEffect, useState } from "react";
import { Download, ScanLine, Search } from "lucide-react";
import { apiClient, getAccessToken } from "../api/client";
import { useAuth } from "../context/AuthContext";
import SoftwareTable, { SoftwareItemRow } from "../components/SoftwareTable";
import InstallerManager from "../components/InstallerManager";
import Button from "../components/ui/Button";

interface Host {
  id: string;
  hostname: string | null;
  ip_address: string | null;
  group_id: string | null;
}

interface HostGroup {
  id: string;
  name: string;
}

interface SummaryRow {
  name: string;
  version: string | null;
  host_count: number;
}

type Tab = "registry" | "summary" | "installers";

const TABS: { id: Tab; label: string }[] = [
  { id: "registry", label: "Реестр" },
  { id: "summary", label: "Сводка" },
  { id: "installers", label: "Установочники" },
];

export default function Software() {
  const { user } = useAuth();
  const canScan = user?.role === "admin" || user?.role === "operator";

  const [tab, setTab] = useState<Tab>("registry");
  const [items, setItems] = useState<SoftwareItemRow[]>([]);
  const [summary, setSummary] = useState<SummaryRow[]>([]);
  const [hosts, setHosts] = useState<Host[]>([]);
  const [groups, setGroups] = useState<HostGroup[]>([]);
  const [nameFilter, setNameFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [excludeSystem, setExcludeSystem] = useState(true);
  const [selectedHostIds, setSelectedHostIds] = useState<string[]>([]);
  const [scanMessage, setScanMessage] = useState<string | null>(null);

  async function loadItems() {
    const { data } = await apiClient.get<SoftwareItemRow[]>("/software", {
      params: {
        name: nameFilter || undefined,
        status_filter: statusFilter || undefined,
        exclude_system: excludeSystem || undefined,
      },
    });
    setItems(data);
  }

  async function loadHostsAndGroups() {
    const [{ data: hostData }, { data: groupData }] = await Promise.all([
      apiClient.get<Host[]>("/hosts"),
      apiClient.get<HostGroup[]>("/hosts/groups"),
    ]);
    setHosts(hostData);
    setGroups(groupData);
  }

  useEffect(() => {
    loadHostsAndGroups();
  }, []);

  useEffect(() => {
    loadItems();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nameFilter, statusFilter, excludeSystem]);

  useEffect(() => {
    if (tab === "summary") {
      apiClient.get<SummaryRow[]>("/software/summary").then((r) => setSummary(r.data));
    }
  }, [tab]);

  function toggleHost(id: string) {
    setSelectedHostIds((prev) => (prev.includes(id) ? prev.filter((h) => h !== id) : [...prev, id]));
  }

  async function triggerScan() {
    if (selectedHostIds.length === 0) return;
    const { data } = await apiClient.post("/software/scan", { host_ids: selectedHostIds });
    setScanMessage(`Сканирование запущено, задача: ${data.task_run_id}`);
  }

  async function downloadExport(format: "csv" | "pdf") {
    const token = getAccessToken();
    const res = await fetch(`${apiClient.defaults.baseURL}/software/export.${format}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `software_inventory.${format}`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="animate-fade-in space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Мониторинг ПО</h1>
        {tab === "registry" && (
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" size="sm" onClick={() => downloadExport("csv")}>
              <Download className="h-3.5 w-3.5" />
              CSV
            </Button>
            <Button variant="secondary" size="sm" onClick={() => downloadExport("pdf")}>
              <Download className="h-3.5 w-3.5" />
              PDF
            </Button>
          </div>
        )}
      </div>

      <div role="tablist" className="inline-flex rounded-lg border border-border bg-muted/40 p-0.5">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`cursor-pointer rounded-md px-3 py-1.5 text-sm font-medium transition-colors duration-150 ${
              tab === t.id
                ? "bg-surface text-foreground shadow-panel"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "registry" && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-subtle" />
              <input
                aria-label="Поиск по названию ПО"
                placeholder="Поиск по названию"
                value={nameFilter}
                onChange={(e) => setNameFilter(e.target.value)}
                className="input-base w-auto py-2 pl-8 text-sm"
              />
            </div>
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="input-base w-auto py-2 text-sm">
              <option value="">Любой статус</option>
              <option value="installed">installed</option>
              <option value="removed">removed</option>
              <option value="unknown">unknown</option>
            </select>
            <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-muted-foreground hover:text-foreground">
              <input
                type="checkbox"
                checked={excludeSystem}
                onChange={(e) => setExcludeSystem(e.target.checked)}
                className="h-3.5 w-3.5 accent-blue-500"
              />
              Скрыть системное ПО
            </label>
          </div>

          {canScan && (
            <div className="surface-panel">
              <h2 className="mb-2 text-sm font-medium text-muted-foreground">Запустить сканирование ПО</h2>
              <div className="mb-3 flex flex-wrap gap-2">
                {hosts.map((h) => (
                  <label key={h.id} className={selectedHostIds.includes(h.id) ? "chip-on" : "chip-off"}>
                    <input type="checkbox" className="sr-only" checked={selectedHostIds.includes(h.id)} onChange={() => toggleHost(h.id)} />
                    {h.hostname || h.ip_address || h.id}
                  </label>
                ))}
              </div>
              <Button onClick={triggerScan} disabled={selectedHostIds.length === 0}>
                <ScanLine className="h-4 w-4" />
                Сканировать выбранные ({selectedHostIds.length})
              </Button>
              {scanMessage && <p className="mt-2 text-sm text-muted-foreground">{scanMessage}</p>}
            </div>
          )}

          <SoftwareTable items={items} hosts={hosts} groups={groups} />
        </>
      )}

      {tab === "summary" && (
        <div className="table-shell">
          <table className="table-base">
            <thead>
              <tr>
                <th>Название</th>
                <th>Версия</th>
                <th>Установлено на хостах</th>
              </tr>
            </thead>
            <tbody>
              {summary.map((s, i) => (
                <tr key={i}>
                  <td className="font-medium text-foreground">{s.name}</td>
                  <td className="font-mono text-foreground/80">{s.version || "—"}</td>
                  <td className="tabular-nums">{s.host_count}</td>
                </tr>
              ))}
              {summary.length === 0 && (
                <tr>
                  <td colSpan={3} className="py-8 text-center text-subtle">
                    Нет данных — запустите сканирование ПО
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {tab === "installers" && <InstallerManager />}
    </div>
  );
}
