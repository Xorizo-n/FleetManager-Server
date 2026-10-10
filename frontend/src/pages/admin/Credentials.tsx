import { FormEvent, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { KeyRound, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { apiClient } from "../../api/client";
import { keys, useCredentials, useFleet } from "../../api/queries";
import type { Credential } from "../../api/types";
import { useAuth } from "../../context/AuthContext";
import PageHeader from "../../components/ui/PageHeader";
import Tabs from "../../components/ui/Tabs";
import Button from "../../components/ui/Button";
import Modal from "../../components/ui/Modal";
import SearchInput from "../../components/ui/SearchInput";
import Checkbox from "../../components/ui/Checkbox";
import { Empty, ErrorText, Loading } from "../../components/ui/States";
import { useToast } from "../../components/ui/Toast";
import { apiError, formatDateTime, plural } from "../../lib/format";

const TYPE_LABELS: Record<string, string> = { ssh_key: "SSH-ключ", password: "Логин и пароль", token: "Токен" };

function usage(c: Credential) {
  const parts = [
    c.host_count ? plural(c.host_count, "хост", "хоста", "хостов") : "",
    c.group_count ? plural(c.group_count, "группа", "группы", "групп") : "",
    c.repo_count ? plural(c.repo_count, "репозиторий", "репозитория", "репозиториев") : "",
  ].filter(Boolean);
  return parts.length ? parts.join(", ") : null;
}

export default function Credentials() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const queryClient = useQueryClient();
  const toast = useToast();
  const credentials = useCredentials();
  const { hosts } = useFleet();
  const [tab, setTab] = useState<"manual" | "agent">("manual");
  const [adding, setAdding] = useState(false);
  const [search, setSearch] = useState("");
  const [unusedOnly, setUnusedOnly] = useState(false);

  const manual = useMemo(() => (credentials.data ?? []).filter((c) => !c.is_agent_managed), [credentials.data]);
  const agentKeys = useMemo(() => (credentials.data ?? []).filter((c) => c.is_agent_managed), [credentials.data]);
  const unused = agentKeys.filter((c) => !usage(c));
  const hostOfKey = useMemo(() => new Map(hosts.filter((h) => h.credential_id).map((h) => [h.credential_id!, h])), [hosts]);

  const shownAgentKeys = agentKeys.filter((c) => (!unusedOnly || !usage(c)) && (!search || c.name.toLowerCase().includes(search.toLowerCase())));

  async function remove(list: Credential[]) {
    const text = list.length === 1 ? `Удалить «${list[0].name}»?` : `Удалить ${plural(list.length, "ключ", "ключа", "ключей")}?`;
    const used = list.filter((c) => usage(c));
    if (!window.confirm(used.length ? `${text}\n\nИспользуются: ${used.map((c) => `${c.name} (${usage(c)})`).join("; ")} — они потеряют доступ.` : text)) return;
    try {
      for (const c of list) await apiClient.delete(`/credentials/${c.id}`);
      queryClient.invalidateQueries({ queryKey: keys.credentials });
      toast({ tone: "success", message: `Удалено: ${list.length}` });
    } catch (err) {
      queryClient.invalidateQueries({ queryKey: keys.credentials });
      toast({ tone: "error", message: apiError(err, "Не удалось удалить") });
    }
  }

  return (
    <div className="animate-fade-in space-y-4">
      <PageHeader
        title="Учётные данные"
        description={
          <span className="inline-flex items-center gap-1.5">
            <ShieldCheck className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
            Секреты хранятся зашифрованными (Fernet) и не возвращаются через API
          </span>
        }
        actions={
          isAdmin && (
            <Button size="sm" onClick={() => setAdding(true)}>
              <Plus className="h-3.5 w-3.5" />
              Добавить
            </Button>
          )
        }
      />
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "manual", label: "Учётные данные", count: manual.length },
          { id: "agent", label: "Ключи агентов", count: agentKeys.length },
        ]}
      />
      {credentials.isLoading && <Loading />}

      {tab === "manual" && !credentials.isLoading && (
        <div className="table-shell">
          <table className="table-base">
            <thead>
              <tr>
                <th>Название</th>
                <th>Тип</th>
                <th>Логин</th>
                <th>Используется</th>
                <th>Создан</th>
                {isAdmin && <th className="w-12" />}
              </tr>
            </thead>
            <tbody>
              {manual.map((c) => (
                <tr key={c.id}>
                  <td className="font-medium text-foreground">
                    <span className="inline-flex items-center gap-2">
                      <KeyRound className="h-3.5 w-3.5 text-subtle" />
                      {c.name}
                    </span>
                  </td>
                  <td>{TYPE_LABELS[c.type]}</td>
                  <td className="font-mono text-xs">{c.login ?? "—"}</td>
                  <td className="text-muted-foreground">{usage(c) ?? <span className="text-subtle">нигде</span>}</td>
                  <td className="text-muted-foreground">{formatDateTime(c.created_at)}</td>
                  {isAdmin && (
                    <td className="text-right">
                      <button className="action-danger" onClick={() => remove([c])} aria-label={`Удалить ${c.name}`}>
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          {manual.length === 0 && <Empty>Учётные данные не добавлены</Empty>}
        </div>
      )}

      {tab === "agent" && !credentials.isLoading && (
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Сервер выпускает SSH-ключ каждому агенту при регистрации. Ключ, который не привязан ни к одному хосту, остался от
            перерегистрации ПК — его можно удалить.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <SearchInput value={search} onChange={setSearch} placeholder="Имя ПК" className="min-w-[200px] flex-1" />
            <label className="flex cursor-pointer items-center gap-2 text-sm text-muted-foreground">
              <Checkbox checked={unusedOnly} onChange={(e) => setUnusedOnly(e.target.checked)} />
              Только неиспользуемые ({unused.length})
            </label>
            {isAdmin && unused.length > 0 && (
              <Button size="sm" variant="secondary" onClick={() => remove(unused)}>
                <Trash2 className="h-3.5 w-3.5" />
                Удалить неиспользуемые ({unused.length})
              </Button>
            )}
          </div>
          <div className="table-shell">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Ключ</th>
                  <th>Хост</th>
                  <th>Логин</th>
                  <th>Выпущен</th>
                  {isAdmin && <th className="w-12" />}
                </tr>
              </thead>
              <tbody>
                {shownAgentKeys.slice(0, 300).map((c) => {
                  const host = hostOfKey.get(c.id);
                  return (
                    <tr key={c.id}>
                      <td className="text-foreground">{c.name.replace(/^Agent SSH — /, "")}</td>
                      <td>{host ? host.hostname : <span className="text-amber-600 dark:text-amber-400">не используется</span>}</td>
                      <td className="font-mono text-xs">{c.login ?? "—"}</td>
                      <td className="text-muted-foreground">{formatDateTime(c.created_at)}</td>
                      {isAdmin && (
                        <td className="text-right">
                          <button className="action-danger" onClick={() => remove([c])} aria-label={`Удалить ${c.name}`}>
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {shownAgentKeys.length > 300 && <p className="px-4 py-2 text-xs text-subtle">Показаны первые 300 из {shownAgentKeys.length} — уточните поиск</p>}
            {shownAgentKeys.length === 0 && <Empty>Ничего не найдено</Empty>}
          </div>
        </div>
      )}

      {adding && <AddCredentialDialog onClose={() => setAdding(false)} />}
    </div>
  );
}

function AddCredentialDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState({ name: "", type: "password", login: "", secret: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiClient.post("/credentials", { ...form, login: form.login || null });
      queryClient.invalidateQueries({ queryKey: keys.credentials });
      toast({ tone: "success", message: `Добавлено: ${form.name}` });
      onClose();
    } catch (err) {
      setError(apiError(err, "Не удалось сохранить"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open onClose={onClose} title="Новые учётные данные" size="md">
      <form onSubmit={submit} className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="cred-name" className="field-label">Название</label>
          <input id="cred-name" required autoFocus value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="input-base" autoComplete="off" />
        </div>
        <div>
          <label htmlFor="cred-type" className="field-label">Тип</label>
          <select id="cred-type" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })} className="input-base">
            {Object.entries(TYPE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </div>
        <div className="sm:col-span-2">
          <label htmlFor="cred-login" className="field-label">Логин</label>
          <input id="cred-login" value={form.login} onChange={(e) => setForm({ ...form, login: e.target.value })} className="input-base" autoComplete="off" />
        </div>
        <div className="sm:col-span-2">
          <label htmlFor="cred-secret" className="field-label">{form.type === "ssh_key" ? "Приватный ключ (PEM)" : form.type === "token" ? "Токен" : "Пароль"}</label>
          <textarea id="cred-secret" required rows={form.type === "ssh_key" ? 6 : 1} value={form.secret} onChange={(e) => setForm({ ...form, secret: e.target.value })} className="input-base font-mono" autoComplete="off" />
        </div>
        <div className="flex items-center justify-end gap-2 sm:col-span-2">
          <ErrorText>{error}</ErrorText>
          <Button type="button" variant="secondary" onClick={onClose}>Отмена</Button>
          <Button type="submit" loading={busy}>Сохранить</Button>
        </div>
      </form>
    </Modal>
  );
}
