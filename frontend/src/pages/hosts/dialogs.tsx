import { FormEvent, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../../api/client";
import { keys, useCredentials, useFleet } from "../../api/queries";
import Modal from "../../components/ui/Modal";
import Button from "../../components/ui/Button";
import { ErrorText } from "../../components/ui/States";
import { useToast } from "../../components/ui/Toast";
import { apiError, OS_OPTIONS, osLabel, pcCount } from "../../lib/format";
import { effectiveCredential, isSshAssignable } from "../../lib/credentials";
import { useAccessChange } from "../../components/useAccessChange";

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
            {(credentials.data ?? []).filter(isSshAssignable).map((c) => <option key={c.id} value={c.id}>{c.name} · {c.login}</option>)}
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
  const { tree, hostById } = useFleet();
  const credentials = useCredentials();
  const runAccessChange = useAccessChange();
  const [mode, setMode] = useState<"existing" | "new" | "none">("existing");
  const [groupId, setGroupId] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await runAccessChange({
        action: "move_to_group",
        host_ids: hostIds,
        ...(mode === "existing" ? { group_id: groupId } : mode === "new" ? { group_name: name.trim() } : { group_id: null }),
      });
      onDone();
    } catch (err) {
      setError(apiError(err, "Не удалось изменить группу"));
    } finally {
      setBusy(false);
    }
  }

  const valid = mode === "none" || (mode === "existing" ? !!groupId : !!name.trim());

  // ПК без своей учётки подключаются учёткой группы: смена группы может её поменять
  const credentialImpact = useMemo(() => {
    let changed = 0;
    let lost = 0;
    const target = mode === "existing" ? groupId || null : null;
    for (const id of hostIds) {
      const host = hostById.get(id);
      if (!host || host.credential_id) continue;
      const before = effectiveCredential(host, tree, credentials.data);
      const after = effectiveCredential({ credential_id: null, group_id: target }, tree, credentials.data);
      const beforeId = before.source === "group" ? before.credentialId : null;
      const afterId = after.source === "group" ? after.credentialId : null;
      if (beforeId !== afterId) {
        changed += 1;
        if (!afterId) lost += 1;
      }
    }
    return { changed, lost };
  }, [mode, groupId, hostIds, hostById, tree, credentials.data]);
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
        {credentialImpact.changed > 0 && (
          <p className={`rounded-lg px-3 py-2 text-xs ${credentialImpact.lost ? "bg-rose-500/10 text-rose-700 dark:text-rose-300" : "bg-amber-500/10 text-amber-700 dark:text-amber-300"}`}>
            У {pcCount(credentialImpact.changed)} нет своей учётки — они подключаются учёткой группы, и она сменится. Перед переносом сервер
            проверит вход новыми данными; ПК, на которых вход не пройдёт, останутся в прежней группе.
            {credentialImpact.lost > 0 && ` ${pcCount(credentialImpact.lost)} останутся без учётных данных — их перенос не пройдёт.`}
          </p>
        )}
      </div>
    </Modal>
  );
}

/** Массовая смена учётки SSH у выбранных ПК: проверяется входом, ПК с агентом пропускаются. */
export function CredentialDialog({ hostIds, onClose, onDone }: { hostIds: string[]; onClose: () => void; onDone: () => void }) {
  const credentials = useCredentials();
  const { hostById } = useFleet();
  const runAccessChange = useAccessChange();
  const [credentialId, setCredentialId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const agentKeys = useMemo(() => new Set((credentials.data ?? []).filter((c) => c.is_agent_managed).map((c) => c.id)), [credentials.data]);
  const withAgentKey = hostIds.filter((id) => agentKeys.has(hostById.get(id)?.credential_id ?? "")).length;
  const changeable = hostIds.length - withAgentKey;

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await runAccessChange({ action: "set_host_credential", host_ids: hostIds, credential_id: credentialId === "__group__" ? null : credentialId });
      onDone();
    } catch (err) {
      setError(apiError(err, "Не удалось изменить учётные данные"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      size="sm"
      title={`Учётные данные SSH для ${pcCount(hostIds.length)}`}
      footer={
        <>
          <ErrorText>{error}</ErrorText>
          <Button variant="secondary" onClick={onClose}>Отмена</Button>
          <Button onClick={submit} loading={busy} disabled={!credentialId || changeable === 0}>Проверить вход и применить</Button>
        </>
      }
    >
      <div className="space-y-3 text-sm">
        <select value={credentialId} onChange={(e) => setCredentialId(e.target.value)} className="input-base" autoFocus aria-label="Учётные данные">
          <option value="">Выберите учётные данные</option>
          <option value="__group__">Как у группы (убрать собственную учётку)</option>
          {(credentials.data ?? []).filter(isSshAssignable).map((c) => <option key={c.id} value={c.id}>{c.name} · {c.login}</option>)}
        </select>
        <p className="text-muted-foreground">
          Сервер войдёт на каждый ПК новыми данными. Где вход пройдёт — учётка сменится, где нет (неверные данные или ПК выключен) —
          останется прежней. Итог по каждому ПК будет в логе задачи.
        </p>
        {withAgentKey > 0 && (
          <p className="rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">
            {pcCount(withAgentKey)} подключаются ключом агента — он не меняется, эти ПК будут пропущены.
          </p>
        )}
      </div>
    </Modal>
  );
}
