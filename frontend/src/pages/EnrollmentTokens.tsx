import { useEffect, useState } from "react";
import { Copy, KeyRound, Trash2 } from "lucide-react";
import { apiClient } from "../api/client";

type EnrollmentToken = {
  id: string;
  name: string;
  expires_at: string | null;
  is_active: boolean;
  created_at: string;
};
type CreatedEnrollmentToken = EnrollmentToken & { raw_token: string };

function formatExpiry(value: string | null) {
  return value ? new Date(value).toLocaleString() : "Без срока";
}

export default function EnrollmentTokens() {
  const [tokens, setTokens] = useState<EnrollmentToken[]>([]);
  const [name, setName] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [newToken, setNewToken] = useState<CreatedEnrollmentToken | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const { data } = await apiClient.get<EnrollmentToken[]>("/agent/enrollment-tokens");
      setTokens(data);
    } catch (err: any) {
      setError(err.response?.data?.detail || "Не удалось загрузить enrollment-токены");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function createToken(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const { data } = await apiClient.post<CreatedEnrollmentToken>("/agent/enrollment-tokens", {
        name: name.trim(),
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
      });
      setNewToken(data);
      setName("");
      setExpiresAt("");
      await load();
    } catch (err: any) {
      setError(err.response?.data?.detail || "Не удалось создать токен");
    } finally {
      setSaving(false);
    }
  }

  async function revokeToken(token: EnrollmentToken) {
    if (!window.confirm(`Удалить токен «${token.name}»? Новые агенты больше не смогут зарегистрироваться.`)) return;
    try {
      await apiClient.delete(`/agent/enrollment-tokens/${token.id}`);
      setTokens((current) =>
        current.map((item) => (item.id === token.id ? { ...item, is_active: false } : item))
      );
    } catch (err: any) {
      setError(err.response?.data?.detail || "Не удалось удалить токен");
    }
  }

  async function copyToken() {
    if (newToken) await navigator.clipboard.writeText(newToken.raw_token);
  }

  return (
    <div className="animate-fade-in space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Токены агентов</h1>
          <p className="mt-1 text-sm text-muted-foreground">Многоразовые токены для автоматического добавления ПК</p>
        </div>
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-500/10 text-blue-600 dark:text-blue-400">
          <KeyRound className="h-5 w-5" aria-hidden="true" />
        </div>
      </div>

      {error && <p role="alert" className="text-sm text-red-500">{error}</p>}

      <form onSubmit={createToken} className="surface-panel grid gap-3 md:grid-cols-[1.3fr_1fr_auto] md:items-end">
        <label className="space-y-1 text-sm">
          <span className="text-muted-foreground">Название</span>
          <input
            className="input-base"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Например, Учебный корпус"
            autoComplete="off"
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-muted-foreground">Действует до</span>
          <input
            className="input-base"
            type="datetime-local"
            value={expiresAt}
            onChange={(e) => setExpiresAt(e.target.value)}
          />
        </label>
        <button className="btn-primary" disabled={saving}>
          {saving ? "Создание…" : "Создать токен"}
        </button>
      </form>

      {newToken && (
        <div className="surface-panel border-blue-500/40 bg-blue-500/5">
          <p className="text-sm font-medium">Токен создан. Скопируйте его сейчас — сервер хранит только хэш.</p>
          <div className="mt-3 flex gap-2">
            <code className="min-w-0 flex-1 break-all rounded-lg bg-background px-3 py-2 text-xs">
              {newToken.raw_token}
            </code>
            <button
              type="button"
              className="btn-secondary btn-sm"
              onClick={copyToken}
              aria-label="Скопировать токен"
            >
              <Copy className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        </div>
      )}

      <div className="table-shell">
        <table className="table-base">
          <thead>
            <tr>
              <th>Название</th>
              <th>Срок действия</th>
              <th>Статус</th>
              <th className="text-right">Действие</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={4} className="px-3 py-8 text-center text-subtle">Загрузка…</td>
              </tr>
            )}
            {!loading && tokens.map((token) => (
              <tr key={token.id}>
                <td className="font-medium">{token.name}</td>
                <td>{formatExpiry(token.expires_at)}</td>
                <td>
                  {token.is_active
                    ? <span className="text-emerald-600 dark:text-emerald-400">Активен</span>
                    : <span className="text-muted-foreground">Отозван</span>}
                </td>
                <td className="text-right">
                  <button
                    type="button"
                    className="action-danger"
                    disabled={!token.is_active}
                    onClick={() => revokeToken(token)}
                    aria-label={`Отозвать токен ${token.name}`}
                  >
                    <Trash2 className="h-4 w-4" aria-hidden="true" />
                  </button>
                </td>
              </tr>
            ))}
            {!loading && tokens.length === 0 && (
              <tr>
                <td colSpan={4} className="px-3 py-8 text-center text-subtle">Токенов пока нет</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
