import { useEffect, useState } from "react";
import { ShieldCheck, UserCog } from "lucide-react";
import { apiClient } from "../api/client";
import { CurrentUser, UserRole, useAuth } from "../context/AuthContext";
import Badge from "../components/ui/Badge";

const ROLE_OPTIONS: { value: UserRole; label: string }[] = [
  { value: "admin", label: "Администратор" },
  { value: "operator", label: "Оператор" },
  { value: "viewer", label: "Наблюдатель" },
];

const ROLE_LABELS: Record<UserRole, string> = Object.fromEntries(
  ROLE_OPTIONS.map((role) => [role.value, role.label]),
) as Record<UserRole, string>;

export default function Users() {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<CurrentUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);

  async function loadUsers() {
    setLoading(true);
    setError(null);
    try {
      const { data } = await apiClient.get<CurrentUser[]>("/users");
      setUsers(data);
    } catch (err: any) {
      setError(err.response?.data?.detail || "Не удалось загрузить пользователей");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadUsers();
  }, []);

  async function handleRoleChange(userId: string, role: UserRole) {
    setSavingId(userId);
    setError(null);
    try {
      const { data } = await apiClient.patch<CurrentUser>(`/users/${userId}/role`, { role });
      setUsers((previous) => previous.map((item) => (item.id === data.id ? data : item)));
    } catch (err: any) {
      setError(err.response?.data?.detail || "Не удалось изменить роль");
    } finally {
      setSavingId(null);
    }
  }

  return (
    <div className="animate-fade-in space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Пользователи</h1>
          <p className="mt-1 text-sm text-muted-foreground">Назначение ролей и прав доступа</p>
        </div>
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-500/10 text-blue-600 dark:text-blue-400">
          <UserCog className="h-5 w-5" />
        </div>
      </div>

      {error && <p className="text-sm text-red-500">{error}</p>}

      <div className="table-shell">
        <table className="table-base">
          <thead>
            <tr>
              <th>Пользователь</th><th>Email</th><th>Роль</th><th>Статус</th><th className="text-right">Изменение прав</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={5} className="px-3 py-8 text-center text-subtle">Загрузка...</td></tr>}
            {!loading && users.map((item) => {
              const isSelf = item.id === currentUser?.id;
              return (
                <tr key={item.id}>
                  <td><div className="flex items-center gap-2"><span className="flex h-7 w-7 items-center justify-center rounded-full bg-muted text-xs font-medium text-foreground">{item.username.slice(0, 1).toUpperCase()}</span><span className="font-medium">{item.username}{isSelf ? " (вы)" : ""}</span></div></td>
                  <td className="text-foreground/70">{item.email}</td>
                  <td><Badge status={item.role === "admin" ? "success" : "info"}>{ROLE_LABELS[item.role]}</Badge></td>
                  <td><Badge status={item.is_active ? "success" : "disabled"}>{item.is_active ? "активен" : "заблокирован"}</Badge></td>
                  <td className="text-right"><select value={item.role} disabled={isSelf || savingId === item.id} onChange={(event) => handleRoleChange(item.id, event.target.value as UserRole)} className="input-base w-auto min-w-40 py-1.5 text-sm disabled:cursor-not-allowed disabled:opacity-50" aria-label={`Роль пользователя ${item.username}`}>
                    {ROLE_OPTIONS.map((role) => <option key={role.value} value={role.value}>{role.label}</option>)}
                  </select></td>
                </tr>
              );
            })}
            {!loading && users.length === 0 && <tr><td colSpan={5} className="px-3 py-8 text-center text-subtle">Пользователей нет</td></tr>}
          </tbody>
        </table>
      </div>

      <div className="surface-panel flex items-start gap-3 text-sm text-muted-foreground"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-blue-600 dark:text-blue-400" /><p>Собственную роль изменить нельзя. Система также не позволит понизить последнего активного администратора.</p></div>
    </div>
  );
}
