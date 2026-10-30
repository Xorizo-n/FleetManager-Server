import { FormEvent, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, RefreshCw, Trash2 } from "lucide-react";
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
      <div className="grid gap-4 xl:grid-cols-2">{query.data.map((p) => <article key={p.id} className="rounded-xl border border-border bg-surface p-5 space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-semibold">{p.name}</h2><p className="text-sm text-muted-foreground">{p.data?.model || "Модель неизвестна"} · {p.address}{p.location ? ` · ${p.location}` : ""}</p>{p.data?.sys_name && <p className="text-xs text-subtle">{p.data.sys_name}</p>}</div><span className={`rounded-full px-2.5 py-1 text-xs font-medium ${p.status === "online" ? "bg-emerald-500/10 text-emerald-600" : p.status === "unreachable" ? "bg-rose-500/10 text-rose-600" : "bg-muted text-muted-foreground"}`}>{p.status === "online" ? "SNMP отвечает" : p.status === "unreachable" ? "Нет ответа SNMP" : "Не проверен"}</span></div>
        <div className="grid grid-cols-2 gap-3 text-sm"><div><span className="text-subtle">Состояние: </span>{p.data?.printer_state ? states[p.data.printer_state] || "Неизвестно" : "Неизвестно"}</div><div><span className="text-subtle">Счётчик: </span>{p.data?.pages ?? "—"}</div></div>
        {!!p.data?.problems.length && <p className="text-sm text-rose-600">{p.data.problems.join(" · ")}</p>}
        {!!p.data?.alerts.length && <div className="text-sm text-muted-foreground">{p.data.alerts.map((a, i) => <div key={i}>{a.message}</div>)}</div>}
        <div className="space-y-2">{p.data?.supplies.length ? p.data.supplies.map((s, i) => <div key={i} className="text-sm"><div className="flex justify-between gap-3"><span>{s.name}</span><span className="tabular-nums">{s.percent === null ? "Неизвестно" : `${s.percent}%`}</span></div>{s.percent !== null && <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted"><div className={`h-full rounded-full ${s.percent <= 10 ? "bg-rose-500" : "bg-blue-500"}`} style={{ width: `${s.percent}%` }} /></div>}</div>) : <p className="text-sm text-subtle">Нет данных о расходниках</p>}</div>
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3"><p className="text-xs text-subtle">Проверен: {date(p.last_checked_at)} · Последний ответ: {date(p.last_seen_at)}{p.status === "unreachable" && p.data ? " · показаны последние полученные данные" : ""}</p>{editable && <div className="flex gap-1"><button className="btn-ghost btn-icon" onClick={() => poll(p)} title="Опросить" aria-label={`Опросить ${p.name}`}><RefreshCw className="h-4 w-4" /></button><button className="btn-ghost btn-icon" onClick={() => setEditing(p)} title="Изменить" aria-label={`Изменить ${p.name}`}><Pencil className="h-4 w-4" /></button><button className="btn-ghost btn-icon" onClick={() => remove(p)} title="Удалить" aria-label={`Удалить ${p.name}`}><Trash2 className="h-4 w-4" /></button></div>}</div>
      </article>)}</div>}
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
    <div><label className="field-label" htmlFor="printer-name">Название</label><input className="input-base" id="printer-name" required maxLength={128} value={name} onChange={e => setName(e.target.value)} /></div>
    <div><label className="field-label" htmlFor="printer-ip">IPv4-адрес</label><input className="input-base" id="printer-ip" required value={address} onChange={e => setAddress(e.target.value)} placeholder="10.152.128.200" /></div>
    <div><label className="field-label" htmlFor="printer-location">Расположение</label><input className="input-base" id="printer-location" maxLength={255} value={location} onChange={e => setLocation(e.target.value)} placeholder="Корпус, аудитория" /></div>
    <div><label className="field-label" htmlFor="printer-community">SNMP community</label><input className="input-base" id="printer-community" type="password" maxLength={128} autoComplete="new-password" value={community} onChange={e => setCommunity(e.target.value)} placeholder={printer ? "Оставьте пустым, чтобы не менять" : "По умолчанию public"} /><p className="mt-1 text-xs text-subtle">SNMP v2c, только чтение. Значение хранится зашифрованным.</p></div>
    <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Отмена</Button><Button type="submit" loading={saving}>Сохранить</Button></div>
  </form></Modal>;
}
