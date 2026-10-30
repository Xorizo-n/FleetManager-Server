import { FormEvent, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ExternalLink, Pencil, Plus, Printer as PrinterIcon, RefreshCw, Trash2 } from "lucide-react";
import { apiClient } from "../api/client";
import { useAuth } from "../context/AuthContext";
import PageHeader from "../components/ui/PageHeader";
import Button from "../components/ui/Button";
import Modal from "../components/ui/Modal";
import { Empty, ErrorText, Loading } from "../components/ui/States";
import { useToast } from "../components/ui/Toast";
import { apiError } from "../lib/format";

type Discovery = { status: "never" | "queued" | "running" | "completed" | "failed" | "interrupted"; started_at?: string; finished_at?: string; rooms_total?: number; rooms_scanned?: number; found?: number; added?: number; failed_rooms?: string[]; message?: string };
type Printer = { id: string; name: string; address: string; location: string | null; status: string; last_checked_at: string | null; last_seen_at: string | null; data: { sys_name: string; model: string | null; printer_state: number | null; pages: number | null; problems: string[]; supplies: { name: string; percent: number | null }[]; alerts: { severity: string; message: string }[] } | null };
const date = (s: string | null) => s ? new Date(s).toLocaleString("ru-RU") : "—";
const states: Record<number, string> = { 1: "Другое", 2: "Неизвестно", 3: "Ожидание", 4: "Печатает", 5: "Прогрев" };

export default function Printers() {
  const { user } = useAuth(); const editable = user?.role === "admin" || user?.role === "operator";
  const toast = useToast(); const client = useQueryClient();
  const [editing, setEditing] = useState<Printer | "new" | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const query = useQuery({ queryKey: ["printers"], queryFn: async () => (await apiClient.get<Printer[]>("/printers")).data, refetchInterval: 15000 });
  const refresh = () => client.invalidateQueries({ queryKey: ["printers"] });
  const discovery = useQuery({ queryKey: ["printer-discovery"], queryFn: async () => (await apiClient.get<Discovery>("/printers/discovery/status")).data, refetchInterval: 5000 });
  const searching = discovery.data?.status === "queued" || discovery.data?.status === "running";
  async function discover() {
    try { await apiClient.post("/printers/discovery"); await client.invalidateQueries({ queryKey: ["printer-discovery"] }); toast({ tone: "info", message: "Поиск принтеров поставлен в очередь" }); }
    catch (e) { toast({ tone: "error", message: apiError(e, "Не удалось запустить поиск") }); }
  }
  async function poll(p: Printer) {
    try { await apiClient.post(`/printers/${p.id}/poll`); toast({ tone: "info", message: "Опрос поставлен в очередь" }); }
    catch (e) { toast({ tone: "error", message: apiError(e, "Не удалось запустить опрос") }); }
  }
  async function remove(p: Printer) {
    if (!window.confirm(`Удалить принтер «${p.name}» из мониторинга?`)) return;
    try { await apiClient.delete(`/printers/${p.id}`); await refresh(); toast({ tone: "success", message: "Принтер удалён" }); }
    catch (e) { toast({ tone: "error", message: apiError(e, "Не удалось удалить принтер") }); }
  }
  return <div className="animate-fade-in space-y-6">
    <PageHeader title="Принтеры" description="Сетевые принтеры · опрос SNMP каждые 5 минут" actions={editable && <><Button size="sm" variant="secondary" onClick={discover} disabled={searching}><RefreshCw className={`h-4 w-4 ${searching ? "animate-spin" : ""}`} />{searching ? "Поиск выполняется" : "Найти принтеры"}</Button><Button size="sm" onClick={() => setEditing("new")}><Plus className="h-4 w-4" />Добавить принтер</Button></>} />
    {discovery.data && discovery.data.status !== "never" && <div className="rounded-xl border border-border bg-surface px-4 py-3 text-sm text-muted-foreground" aria-live="polite">
      {discovery.data.status === "queued" ? "Поиск ожидает запуска" : discovery.data.status === "running" ? "Идёт поиск через ПК в аудиториях…" : discovery.data.status === "completed" ? <>Последний поиск: {date(discovery.data.finished_at ?? null)} · аудиторий проверено {discovery.data.rooms_scanned} из {discovery.data.rooms_total} · найдено {discovery.data.found} · добавлено {discovery.data.added}{!!discovery.data.failed_rooms?.length && <span title={discovery.data.failed_rooms.join(", ")}> · не проверены: {discovery.data.failed_rooms.join(", ")}</span>}</> : discovery.data.message || "Поиск прерван; запустите повторно"}
    </div>}
    {query.isLoading ? <Loading /> : query.isError ? <ErrorText>Не удалось загрузить принтеры</ErrorText> : !query.data?.length ? <div className="table-shell"><Empty>Принтеры ещё не добавлены</Empty></div> :
      <div className="overflow-hidden rounded-xl border border-border bg-surface">
        <div className="hidden grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.5fr)_auto] gap-4 border-b border-border bg-muted/40 px-4 py-2 text-xs font-medium text-subtle lg:grid">
          <span>Принтер</span><span>Расположение</span><span>Связь и состояние</span><span>Расходники</span><span className="w-36 text-right">Действия</span>
        </div>
        {query.data.map((p) => {
          const expanded = expandedId === p.id;
          return <article key={p.id} className="border-b border-border last:border-b-0">
            <div className="grid gap-2 px-4 py-3 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.5fr)_auto] lg:items-center lg:gap-4">
              <button type="button" onClick={() => setExpandedId(expanded ? null : p.id)} aria-expanded={expanded} aria-label={`${expanded ? "Скрыть" : "Показать"} сведения о ${p.name}`} className="flex min-w-0 items-start gap-2 text-left hover:text-blue-600">
                <PrinterIcon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                <span className="min-w-0"><span className="block truncate text-sm font-medium" title={p.name}>{p.name}</span><span className="block truncate text-xs text-muted-foreground" title={`${p.data?.model || "Модель неизвестна"} · ${p.address}`}>{p.data?.model || "Модель неизвестна"} · {p.address}</span></span>
                <ChevronDown className={`ml-auto mt-0.5 h-4 w-4 shrink-0 text-subtle transition-transform ${expanded ? "rotate-180" : ""}`} />
              </button>
              <p className="text-sm text-muted-foreground">{p.location || "Расположение не указано"}</p>
              <div className="text-sm"><span className={`font-medium ${p.status === "online" ? "text-emerald-600 dark:text-emerald-400" : p.status === "unreachable" ? "text-rose-600 dark:text-rose-400" : "text-muted-foreground"}`}>{p.status === "online" ? "SNMP отвечает" : p.status === "unreachable" ? "Нет ответа SNMP" : "Не проверен"}</span><span className="block text-xs text-subtle">{p.data?.printer_state ? states[p.data.printer_state] || "Неизвестно" : "Состояние неизвестно"}{p.status === "unreachable" && p.data ? " · старые данные" : ""}{!!p.data?.problems.length && ` · ${p.data.problems.join(", ")}`}</span></div>
              <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">{p.data?.supplies.length ? p.data.supplies.map((s, i) => <span key={i} title={s.name}>{s.name}: <strong className={s.percent !== null && s.percent <= 10 ? "text-rose-600" : "text-foreground"}>{s.percent === null ? "—" : `${s.percent}%`}</strong></span>) : <span className="text-subtle">Нет данных</span>}</div>
              <div className="flex w-36 items-center justify-end gap-1">
                <a className="btn-ghost btn-icon" href={`http://${p.address}/`} target="_blank" rel="noopener noreferrer" title="Открыть веб-интерфейс" aria-label={`Открыть веб-интерфейс ${p.name}`}><ExternalLink className="h-4 w-4" /></a>
                {editable && <><button className="btn-ghost btn-icon" onClick={() => poll(p)} title="Опросить" aria-label={`Опросить ${p.name}`}><RefreshCw className="h-4 w-4" /></button><button className="btn-ghost btn-icon" onClick={() => setEditing(p)} title="Изменить" aria-label={`Изменить ${p.name}`}><Pencil className="h-4 w-4" /></button><button className="btn-ghost btn-icon" onClick={() => remove(p)} title="Удалить" aria-label={`Удалить ${p.name}`}><Trash2 className="h-4 w-4" /></button></>}
              </div>
            </div>
            {expanded && <div className="space-y-2 border-t border-border bg-muted/20 px-4 py-3 text-sm text-muted-foreground">
              <p>Счётчик: {p.data?.pages ?? "—"}{p.data?.sys_name && ` · Имя SNMP: ${p.data.sys_name}`}</p>
              {!!p.data?.problems.length && <p className="text-rose-600 dark:text-rose-400">{p.data.problems.join(" · ")}</p>}
              {!!p.data?.alerts.length && <div>{p.data.alerts.map((a, i) => <p key={i}>{a.message}</p>)}</div>}
              <p className="text-xs text-subtle">Проверен: {date(p.last_checked_at)} · Последний ответ: {date(p.last_seen_at)}{p.status === "unreachable" && p.data ? " · показаны последние полученные данные" : ""}</p>
            </div>}
          </article>;
        })}
      </div>}
    {editing && <PrinterForm printer={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={refresh} />}
  </div>;
}

function PrinterForm({ printer, onClose, onSaved }: { printer: Printer | null; onClose: () => void; onSaved: () => Promise<unknown> }) {
  const [name, setName] = useState(printer?.name ?? ""); const [address, setAddress] = useState(printer?.address ?? ""); const [location, setLocation] = useState(printer?.location ?? ""); const [community, setCommunity] = useState(""); const [saving, setSaving] = useState(false); const toast = useToast();
  async function save(e: FormEvent) { e.preventDefault(); setSaving(true); try {
    const payload = { name, address, location: location || null, community: community || null };
    const result = printer ? await apiClient.put<Printer>(`/printers/${printer.id}`, payload) : await apiClient.post<Printer>("/printers", payload);
    await onSaved(); onClose();
    try { await apiClient.post(`/printers/${result.data.id}/poll`); toast({ tone: "success", message: "Принтер сохранён, опрос поставлен в очередь" }); }
    catch { toast({ tone: "info", message: "Принтер сохранён; опрос выполнится по расписанию" }); }
  } catch (err) { toast({ tone: "error", message: apiError(err, "Не удалось сохранить принтер") }); } finally { setSaving(false); } }
  return <Modal open onClose={onClose} title={printer ? "Изменить принтер" : "Добавить принтер"} size="sm"><form onSubmit={save} className="space-y-4">
    <div><label className="field-label" htmlFor="printer-name">Название</label><input className="input-base" id="printer-name" required maxLength={128} value={name} onChange={e => setName(e.target.value)} /><p className="mt-1 text-xs text-subtle">При следующем успешном опросе имя обновится по данным принтера.</p></div>
    <div><label className="field-label" htmlFor="printer-ip">IPv4-адрес</label><input className="input-base" id="printer-ip" required value={address} onChange={e => setAddress(e.target.value)} placeholder="10.152.128.200" /></div>
    <div><label className="field-label" htmlFor="printer-location">Расположение</label><input className="input-base" id="printer-location" maxLength={255} value={location} onChange={e => setLocation(e.target.value)} placeholder="Корпус, аудитория" /></div>
    <div><label className="field-label" htmlFor="printer-community">SNMP community</label><input className="input-base" id="printer-community" type="password" maxLength={128} autoComplete="new-password" value={community} onChange={e => setCommunity(e.target.value)} placeholder={printer ? "Оставьте пустым, чтобы не менять" : "По умолчанию public"} /><p className="mt-1 text-xs text-subtle">SNMP v2c, только чтение. Значение хранится зашифрованным.</p></div>
    <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Отмена</Button><Button type="submit" loading={saving}>Сохранить</Button></div>
  </form></Modal>;
}
