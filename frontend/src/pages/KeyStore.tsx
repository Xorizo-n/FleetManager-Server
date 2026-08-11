import { FormEvent, useEffect, useState } from "react";
import { KeyRound, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { apiClient } from "../api/client";
import { useAuth } from "../context/AuthContext";
import Button from "../components/ui/Button";

interface Credential {
  id: string;
  name: string;
  type: "ssh_key" | "password" | "token";
  login: string | null;
  created_at: string;
}

const TYPE_LABELS: Record<string, string> = {
  ssh_key: "SSH-ключ",
  password: "Логин/пароль",
  token: "Токен",
};

export default function KeyStore() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: "", type: "password", login: "", secret: "" });

  async function load() {
    const { data } = await apiClient.get<Credential[]>("/credentials");
    setCredentials(data);
  }

  useEffect(() => {
    load();
  }, []);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    await apiClient.post("/credentials", form);
    setForm({ name: "", type: "password", login: "", secret: "" });
    setShowForm(false);
    load();
  }

  async function handleDelete(id: string) {
    if (!confirm("Удалить credential? Хосты, использующие его, потеряют доступ к учётным данным.")) return;
    await apiClient.delete(`/credentials/${id}`);
    load();
  }

  if (!isAdmin) {
    return <p className="text-muted-foreground">Key Store доступен только администраторам.</p>;
  }

  return (
    <div className="animate-fade-in space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Key Store</h1>
        <Button size="sm" onClick={() => setShowForm((v) => !v)}>
          <Plus className="h-3.5 w-3.5" />
          Добавить credential
        </Button>
      </div>

      <div className="flex items-start gap-2 rounded-lg border border-border bg-muted/40 p-3 text-sm text-muted-foreground">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
        Секреты хранятся в БД в зашифрованном виде (Fernet) и никогда не возвращаются через API в открытом виде.
      </div>

      {showForm && (
        <form onSubmit={handleCreate} className="surface-panel grid animate-slide-up grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor="cred-name" className="field-label">Название</label>
            <input id="cred-name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="input-base" autoComplete="off" />
          </div>
          <div>
            <label htmlFor="cred-type" className="field-label">Тип</label>
            <select id="cred-type" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })} className="input-base">
              <option value="password">Логин/пароль</option>
              <option value="ssh_key">SSH-ключ</option>
              <option value="token">Токен</option>
            </select>
          </div>
          <div>
            <label htmlFor="cred-login" className="field-label">Логин</label>
            <input id="cred-login" value={form.login} onChange={(e) => setForm({ ...form, login: e.target.value })} className="input-base" autoComplete="username" />
          </div>
          <div className="sm:col-span-2">
            <label htmlFor="cred-secret" className="field-label">{form.type === "ssh_key" ? "Приватный ключ (PEM)" : form.type === "token" ? "Токен" : "Пароль"}</label>
            <textarea
              id="cred-secret"
              required
              value={form.secret}
              onChange={(e) => setForm({ ...form, secret: e.target.value })}
              className="input-base font-mono"
              rows={form.type === "ssh_key" ? 6 : 1}
              autoComplete="off"
            />
          </div>
          <Button type="submit" className="sm:col-span-2">Сохранить</Button>
        </form>
      )}

      <div className="table-shell">
        <table className="table-base">
          <thead>
            <tr>
              <th>Название</th>
              <th>Тип</th>
              <th>Логин</th>
              <th>Создан</th>
              <th className="text-right">Действия</th>
            </tr>
          </thead>
          <tbody>
            {credentials.map((c) => (
              <tr key={c.id}>
                <td className="font-medium text-foreground">
                  <span className="inline-flex items-center gap-2">
                    <KeyRound className="h-3.5 w-3.5 text-subtle" />
                    {c.name}
                  </span>
                </td>
                <td>{TYPE_LABELS[c.type]}</td>
                <td>{c.login || "—"}</td>
                <td className="text-muted-foreground">{new Date(c.created_at).toLocaleString()}</td>
                <td className="text-right">
                  <button
                    onClick={() => handleDelete(c.id)}
                    className="action-danger"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    Удалить
                  </button>
                </td>
              </tr>
            ))}
            {credentials.length === 0 && (
              <tr><td colSpan={5} className="px-3 py-8 text-center text-subtle">Credentials не добавлены</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
