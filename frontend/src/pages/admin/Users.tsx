import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../../api/client";
import { CurrentUser, UserRole, useAuth } from "../../context/AuthContext";
import PageHeader from "../../components/ui/PageHeader";
import Badge from "../../components/ui/Badge";
import { Empty, Loading } from "../../components/ui/States";
import { useToast } from "../../components/ui/Toast";
import { apiError } from "../../lib/format";

const ROLE_OPTIONS: { value: UserRole; label: string; hint: string }[] = [
  { value: "admin", label: "Администратор", hint: "всё, включая пользователей и учётные данные" },
  { value: "operator", label: "Оператор", hint: "запуск плейбуков, управление хостами" },
  { value: "viewer", label: "Наблюдатель", hint: "только просмотр" },
];

export default function Users() {
  const { user: me } = useAuth();
  const queryClient = useQueryClient();
  const toast = useToast();
  const users = useQuery({ queryKey: ["users"], queryFn: () => apiClient.get<CurrentUser[]>("/users").then((r) => r.data) });

  async function changeRole(target: CurrentUser, role: UserRole) {
    try {
      await apiClient.patch(`/users/${target.id}/role`, { role });
      queryClient.invalidateQueries({ queryKey: ["users"] });
      toast({ tone: "success", message: `${target.username}: роль изменена` });
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось изменить роль") });
    }
  }

  async function resetTotp(target: CurrentUser) {
    if (!window.confirm(`Сбросить второй фактор у ${target.username}? При следующем входе пользователь заново привяжет приложение по QR-коду.`)) return;
    try {
      await apiClient.post(`/auth/totp/reset/${target.id}`);
      queryClient.invalidateQueries({ queryKey: ["users"] });
      toast({ tone: "success", message: `TOTP сброшен: ${target.username}` });
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось сбросить TOTP") });
    }
  }

  return (
    <div className="animate-fade-in space-y-4">
      <PageHeader
        title="Пользователи"
        description="Роли и второй фактор. Свою роль изменить нельзя, последнего активного администратора понизить тоже нельзя."
      />
      <div className="table-shell">
        <table className="table-base">
          <thead>
            <tr>
              <th>Пользователь</th>
              <th>Email</th>
              <th>Роль</th>
              <th>TOTP</th>
              <th>Статус</th>
            </tr>
          </thead>
          <tbody>
            {(users.data ?? []).map((u) => {
              const self = u.id === me?.id;
              return (
                <tr key={u.id}>
                  <td className="font-medium text-foreground">
                    {u.username}
                    {self && <span className="ml-1 text-xs font-normal text-subtle">(вы)</span>}
                  </td>
                  <td className="text-muted-foreground">{u.email}</td>
                  <td>
                    <select
                      value={u.role}
                      disabled={self}
                      onChange={(e) => changeRole(u, e.target.value as UserRole)}
                      className="input-base w-auto min-w-40 py-1.5"
                      aria-label={`Роль ${u.username}`}
                      title={ROLE_OPTIONS.find((r) => r.value === u.role)?.hint}
                    >
                      {ROLE_OPTIONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                    </select>
                  </td>
                  <td>
                    {u.totp_enabled ? (
                      <span className="inline-flex items-center gap-2">
                        <Badge status="success">привязан</Badge>
                        {!self && (
                          <button className="text-xs text-muted-foreground hover:text-foreground hover:underline" onClick={() => resetTotp(u)}>
                            сбросить
                          </button>
                        )}
                      </span>
                    ) : (
                      <Badge status="disabled">не привязан</Badge>
                    )}
                  </td>
                  <td>
                    <Badge status={u.is_active ? "success" : "disabled"}>{u.is_active ? "активен" : "заблокирован"}</Badge>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {users.isLoading && <Loading />}
        {users.data?.length === 0 && <Empty>Пользователей нет</Empty>}
      </div>
    </div>
  );
}
