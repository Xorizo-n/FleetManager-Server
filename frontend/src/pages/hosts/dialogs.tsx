import { FormEvent, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../../api/client";
import { keys, useCredentials, useFleet } from "../../api/queries";
import Modal from "../../components/ui/Modal";
import Button from "../../components/ui/Button";
import { ErrorText } from "../../components/ui/States";
import { useToast } from "../../components/ui/Toast";
import { apiError, OS_OPTIONS, osLabel, pcCount } from "../../lib/format";

export function AddHostDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { tree } = useFleet();
  const credentials = useCredentials();
  const [form, setForm] = useState({ hostname: "", ip_address: "", os: OS_OPTIONS[1], group_id: "", credential_id: "", comment: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!form.hostname.trim() && !form.ip_address.trim()) {
      setError("Укажите имя хоста или IP-адрес");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await apiClient.post("/hosts", {
        hostname: form.hostname.trim() || null,
        ip_address: form.ip_address.trim() || null,
        os: form.os,
        group_id: form.group_id || null,
        credential_id: form.credential_id || null,
        comment: form.comment.trim() || null,
      });
      queryClient.invalidateQueries({ queryKey: keys.hosts });
      toast({ tone: "success", message: `Хост ${form.hostname || form.ip_address} добавлен` });
      onClose();
    } catch (err) {
      setError(apiError(err, "Не удалось добавить хост"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open onClose={onClose} title="Добавить хост вручную" size="md">
      <form onSubmit={submit} className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <p className="text-sm text-muted-foreground sm:col-span-2">
          ПК с установленным агентом появляются в реестре сами. Вручную добавляют машины без агента.
        </p>
        <div>
          <label className="field-label" htmlFor="add-hostname">Имя хоста</label>
          <input id="add-hostname" autoFocus value={form.hostname} onChange={(e) => setForm({ ...form, hostname: e.target.value })} className="input-base" placeholder="MR32-411-01" />
        </div>
        <div>
          <label className="field-label" htmlFor="add-ip">IP-адрес</label>
          <input id="add-ip" value={form.ip_address} onChange={(e) => setForm({ ...form, ip_address: e.target.value })} className="input-base font-mono" placeholder="10.40.1.20" />
        </div>
        <div>
          <label className="field-label" htmlFor="add-os">ОС</label>
          <select id="add-os" value={form.os} onChange={(e) => setForm({ ...form, os: e.target.value })} className="input-base">
            {OS_OPTIONS.map((o) => <option key={o} value={o}>{osLabel(o)}</option>)}
          </select>
        </div>
        <div>
          <label className="field-label" htmlFor="add-group">Группа</label>
          <select id="add-group" value={form.group_id} onChange={(e) => setForm({ ...form, group_id: e.target.value })} className="input-base">
            <option value="">Определить по имени / без группы</option>
            {tree.options.map((g) => <option key={g.id} value={g.id}>{g.label}</option>)}
          </select>
        </div>
        <div>
          <label className="field-label" htmlFor="add-cred">Учётные данные SSH</label>
          <select id="add-cred" value={form.credential_id} onChange={(e) => setForm({ ...form, credential_id: e.target.value })} className="input-base">
            <option value="">Наследовать от группы</option>
            {(credentials.data ?? []).filter((c) => !c.is_agent_managed).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
        <div>
          <label className="field-label" htmlFor="add-comment">Комментарий</label>
          <input id="add-comment" value={form.comment} onChange={(e) => setForm({ ...form, comment: e.target.value })} className="input-base" />
        </div>
        <div className="flex items-center justify-end gap-2 sm:col-span-2">
          <ErrorText>{error}</ErrorText>
          <Button type="button" variant="secondary" onClick={onClose}>Отмена</Button>
          <Button type="submit" loading={busy}>Добавить</Button>
        </div>
      </form>
    </Modal>
  );
}

export function GroupDialog({ hostIds, onClose, onDone }: { hostIds: string[]; onClose: () => void; onDone: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { tree } = useFleet();
  const [mode, setMode] = useState<"existing" | "new" | "none">("existing");
  const [groupId, setGroupId] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      if (mode === "none") await apiClient.post("/hosts/groups/unassign", { host_ids: hostIds });
      else await apiClient.post("/hosts/groups/assign", { host_ids: hostIds, ...(mode === "existing" ? { group_id: groupId } : { group_name: name.trim() }) });
      await Promise.all([queryClient.invalidateQueries({ queryKey: keys.hosts }), queryClient.invalidateQueries({ queryKey: keys.groups })]);
      toast({ tone: "success", message: mode === "none" ? `${pcCount(hostIds.length)} убраны из групп` : `Группа назначена: ${pcCount(hostIds.length)}` });
      onDone();
    } catch (err) {
      setError(apiError(err, "Не удалось изменить группу"));
    } finally {
      setBusy(false);
    }
  }

  const valid = mode === "none" || (mode === "existing" ? !!groupId : !!name.trim());
  return (
    <Modal
      open
      onClose={onClose}
      size="sm"
      title={`Группа для ${pcCount(hostIds.length)}`}
      footer={
        <>
          <ErrorText>{error}</ErrorText>
          <Button variant="secondary" onClick={onClose}>Отмена</Button>
          <Button onClick={submit} loading={busy} disabled={!valid}>Применить</Button>
        </>
      }
    >
      <div className="space-y-3 text-sm">
        <label className="flex items-center gap-2">
          <input type="radio" checked={mode === "existing"} onChange={() => setMode("existing")} className="accent-blue-600" />
          Существующая группа
        </label>
        {mode === "existing" && (
          <select value={groupId} onChange={(e) => setGroupId(e.target.value)} className="input-base" autoFocus>
            <option value="">Выберите группу</option>
            {tree.options.map((g) => <option key={g.id} value={g.id}>{g.label}</option>)}
          </select>
        )}
        <label className="flex items-center gap-2">
          <input type="radio" checked={mode === "new"} onChange={() => setMode("new")} className="accent-blue-600" />
          Новая группа
        </label>
        {mode === "new" && <input value={name} onChange={(e) => setName(e.target.value)} className="input-base" placeholder="Например, Преподаватели" autoFocus />}
        <label className="flex items-center gap-2">
          <input type="radio" checked={mode === "none"} onChange={() => setMode("none")} className="accent-blue-600" />
          Убрать из группы
        </label>
        <p className="text-xs text-subtle">ПК с именем по схеме (КОРПУС-АУДИТОРИЯ-ТИП) сервер раскладывает по аудиториям сам; ручная группа с другим именем сохраняется.</p>
      </div>
    </Modal>
  );
}
