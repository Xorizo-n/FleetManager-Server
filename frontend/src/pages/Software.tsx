import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Download, MoreHorizontal, Play } from "lucide-react";
import { useCanEdit, useFleet, usePackageHosts, useSoftwarePackages } from "../api/queries";
import type { Host, SoftwarePackage } from "../api/types";
import PageHeader from "../components/ui/PageHeader";
import SearchInput from "../components/ui/SearchInput";
import Checkbox from "../components/ui/Checkbox";
import Button from "../components/ui/Button";
import Drawer from "../components/ui/Drawer";
import Modal from "../components/ui/Modal";
import Menu from "../components/ui/Menu";
import Tabs from "../components/ui/Tabs";
import { Empty, Loading } from "../components/ui/States";
import PlaybookRunForm from "../components/PlaybookRunForm";
import { StatusDot } from "./hosts/HostTable";
import { downloadFromApi } from "../lib/download";
import { hostLabel, pcCount } from "../lib/format";
import { useDebounced } from "../lib/useDebounced";

const PAGE = 150;

export default function Software() {
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounced(search.trim());
  const [hideSystem, setHideSystem] = useState(true);
  const [limit, setLimit] = useState(PAGE);
  const { hosts } = useFleet();
  const { data, isLoading, isFetching } = useSoftwarePackages({ name: debouncedSearch, exclude_system: hideSystem });
  const agents = hosts.filter((h) => h.has_agent).length || 1;
  const openName = params.get("package");

  const setPackage = (name: string | null) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (name) next.set("package", name);
      else next.delete("package");
      return next;
    });

  const packages = data ?? [];

  return (
    <div className="animate-fade-in space-y-4">
      <PageHeader
        title="ПО"
        description="Каталог установленного ПО по данным агентов: на скольких ПК стоит пакет и в каких версиях"
        actions={
          <Menu
            trigger={({ toggle }) => (
              <button className="btn-secondary btn-sm" onClick={toggle} aria-label="Экспорт">
                <Download className="h-3.5 w-3.5" />
                Экспорт
                <MoreHorizontal className="h-3.5 w-3.5" />
              </button>
            )}
            items={[
              { label: "Полный реестр в CSV", onClick: () => downloadFromApi("/software/export.csv", "software_inventory.csv") },
              { label: "Полный реестр в PDF", onClick: () => downloadFromApi("/software/export.pdf", "software_inventory.pdf") },
            ]}
          />
        }
      />

      <div className="flex flex-wrap items-center gap-3">
        <SearchInput value={search} onChange={(v) => { setSearch(v); setLimit(PAGE); }} placeholder="Название пакета" className="min-w-[240px] flex-1" />
        <label className="flex cursor-pointer items-center gap-2 text-sm text-muted-foreground">
          <Checkbox checked={hideSystem} onChange={(e) => setHideSystem(e.target.checked)} />
          Скрыть системное ПО Microsoft
        </label>
        <span className="text-sm text-muted-foreground">{isFetching && !isLoading ? "Обновление…" : `${packages.length} пакетов`}</span>
      </div>

      <div className="table-shell">
        <table className="table-base">
          <thead>
            <tr>
              <th>Пакет</th>
              <th className="w-56">Установлен</th>
              <th>Версии</th>
            </tr>
          </thead>
          <tbody>
            {packages.slice(0, limit).map((p) => (
              <tr key={p.name} className="is-interactive" tabIndex={0} onClick={() => setPackage(p.name)} onKeyDown={(e) => e.key === "Enter" && setPackage(p.name)}>
                <td className="font-medium text-foreground">{p.name}</td>
                <td>
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 w-24 overflow-hidden rounded-full bg-muted">
                      <div className="h-full rounded-full bg-blue-500" style={{ width: `${Math.min(100, (p.host_count / agents) * 100)}%` }} />
                    </div>
                    <span className="tabular-nums text-muted-foreground">{pcCount(p.host_count)}</span>
                  </div>
                </td>
                <td>
                  <div className="flex flex-wrap items-center gap-1.5">
                    {p.versions.slice(0, 3).map((v) => (
                      <span key={v.version ?? "none"} className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-xs text-foreground/80">
                        {v.version ?? "без версии"} <span className="text-subtle">×{v.host_count}</span>
                      </span>
                    ))}
                    {p.versions.length > 3 && <span className="text-xs text-subtle">+{p.versions.length - 3}</span>}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {isLoading && <Loading />}
        {!isLoading && packages.length === 0 && <Empty>{search ? "Ничего не найдено" : "Данных нет — агенты ещё не прислали инвентаризацию"}</Empty>}
      </div>
      {packages.length > limit && (
        <div className="flex justify-center">
          <Button variant="secondary" onClick={() => setLimit((l) => l + PAGE)}>Показать ещё ({packages.length - limit})</Button>
        </div>
      )}

      {openName && <PackageDrawer name={openName} summary={packages.find((p) => p.name === openName)} onClose={() => setPackage(null)} />}
    </div>
  );
}

function PackageDrawer({ name, summary, onClose }: { name: string; summary?: SoftwarePackage; onClose: () => void }) {
  const canEdit = useCanEdit();
  const { hosts, hostById, tree } = useFleet();
  const { data, isLoading } = usePackageHosts(name);
  const [tab, setTab] = useState<"installed" | "missing">("installed");
  const [version, setVersion] = useState<string>("");
  const [runFor, setRunFor] = useState<string[] | null>(null);

  const installed = useMemo(() => {
    const rows: { host: Host; version: string | null }[] = [];
    for (const item of data ?? []) {
      const host = hostById.get(item.host_id);
      if (host) rows.push({ host, version: item.version });
    }
    return rows.sort((a, b) => hostLabel(a.host).localeCompare(hostLabel(b.host), "ru", { numeric: true }));
  }, [data, hostById]);

  // ПК с агентом, где пакета нет: кандидаты на установку
  const missing = useMemo(() => {
    const has = new Set(installed.map((r) => r.host.id));
    return hosts.filter((h) => h.has_agent && !has.has(h.id)).sort((a, b) => hostLabel(a).localeCompare(hostLabel(b), "ru", { numeric: true }));
  }, [hosts, installed]);

  const versions = useMemo(() => {
    const counts = new Map<string, number>();
    installed.forEach((r) => counts.set(r.version ?? "", (counts.get(r.version ?? "") ?? 0) + 1));
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [installed]);

  const list: { host: Host; version: string | null }[] =
    tab === "installed" ? installed.filter((r) => !version || (r.version ?? "") === version) : missing.map((host) => ({ host, version: null }));

  return (
    <Drawer open onClose={onClose} title={name} subtitle={summary ? `Установлен на ${pcCount(summary.host_count)}` : undefined} width="lg">
      {isLoading ? (
        <Loading />
      ) : (
        <div className="space-y-4">
          <Tabs
            value={tab}
            onChange={(t) => { setTab(t); setVersion(""); }}
            tabs={[
              { id: "installed", label: "Установлен", count: installed.length },
              { id: "missing", label: "Не установлен (с агентом)", count: missing.length },
            ]}
          />
          {tab === "installed" && versions.length > 1 && (
            <div className="flex flex-wrap gap-1.5">
              <button className={!version ? "chip-on" : "chip-off"} onClick={() => setVersion("")}>Все версии</button>
              {versions.map(([v, count]) => (
                <button key={v} className={version === v ? "chip-on" : "chip-off"} onClick={() => setVersion(v)}>
                  <span className="font-mono">{v || "без версии"}</span>
                  <span className="ml-1 text-subtle">×{count}</span>
                </button>
              ))}
            </div>
          )}
          {canEdit && list.length > 0 && (
            <div className="flex items-center justify-between gap-2 rounded-lg border border-border bg-muted/30 px-3 py-2 text-sm">
              <span className="text-muted-foreground">
                {tab === "installed" ? "Обновить или удалить пакет на этих ПК" : "Установить пакет на эти ПК"}
              </span>
              <Button size="sm" onClick={() => setRunFor(list.map((r) => r.host.id))}>
                <Play className="h-3.5 w-3.5" />
                Плейбук на {pcCount(list.length)}
              </Button>
            </div>
          )}
          <div className="table-shell">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Хост</th>
                  <th>Группа</th>
                  {tab === "installed" && <th>Версия</th>}
                  <th>Статус</th>
                </tr>
              </thead>
              <tbody>
                {list.slice(0, 500).map(({ host, version: v }) => (
                  <tr key={host.id}>
                    <td className="font-medium text-foreground">{hostLabel(host)}</td>
                    <td className="max-w-[200px] truncate text-muted-foreground">{tree.pathOf(host.group_id)}</td>
                    {tab === "installed" && <td className="font-mono text-xs">{v ?? "—"}</td>}
                    <td><StatusDot status={host.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {list.length > 500 && <p className="px-4 py-2 text-xs text-subtle">Показаны первые 500 из {list.length}</p>}
            {list.length === 0 && <Empty>Нет хостов</Empty>}
          </div>
        </div>
      )}
      {runFor && (
        <Modal open onClose={() => setRunFor(null)} title={`Запуск плейбука: ${name}`} size="lg">
          <PlaybookRunForm initialHostIds={runFor} onDone={() => setRunFor(null)} pickerHeight={260} />
        </Modal>
      )}
    </Drawer>
  );
}
