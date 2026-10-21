import { FormEvent, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, EyeOff, KeyRound, UserPlus } from "lucide-react";
import { apiClient } from "../../api/client";
import { CurrentUser, UserRole, useAuth } from "../../context/AuthContext";
import PageHeader from "../../components/ui/PageHeader";
import Badge from "../../components/ui/Badge";
import Button from "../../components/ui/Button";
import { Empty, Loading } from "../../components/ui/States";
import { useToast } from "../../components/ui/Toast";
import { apiError } from "../../lib/format";

const ROLE_OPTIONS: { value: UserRole; label: string; hint: string }[] = [
  { value: "admin", label: "Администратор", hint: "всё, включая пользователей и учётные данные" },
  { value: "operator", label: "Оператор", hint: "запуск плейбуков, управление хостами" },
  { value: "viewer", label: "Наблюдатель", hint: "только просмотр" },
  { value: "monitoring", label: "Мониторинг", hint: "дашборд мониторинга с алертами и звуком" },
];

const roleLabel = (role: UserRole) => ROLE_OPTIONS.find((r) => r.value === role)?.label ?? role;

function PasswordInput({
  id,
  value,
  onChange,
  autoComplete,
  minLength = 8,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete: string;
  minLength?: number;
}) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <input
        id={id}
        type={show ? "text" : "password"}
        autoComplete={autoComplete}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required
        minLength={minLength}
        className="input-base pr-10"
      />
      <button
        type="button"
        onClick={() => setShow((v) => !v)}
        className="absolute inset-y-0 right-0 flex items-center px-3 text-subtle transition-colors hover:text-foreground"
        aria-label={show ? "Скрыть пароль" : "Показать пароль"}
      >
        {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </button>
    </div>
  );
}

export default function Users() {
  const { user: me } = useAuth();
  const queryClient = useQueryClient();
  const toast = useToast();
  const users = useQuery({ queryKey: ["users"], queryFn: () => apiClient.get<CurrentUser[]>("/users").then((r) => r.data) });

  const isAdmin = me?.role === "admin";
  const domainSelf = me?.auth_source === "ldap";
  const [createForm, setCreateForm] = useState({ username: "", email: "", password: "", role: "viewer" as UserRole });
  const [creating, setCreating] = useState(false);
  const [pwdForm, setPwdForm] = useState({ current_password: "", new_password: "" });
  const [pwdSaving, setPwdSaving] = useState(false);

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

  async function createUser(e: FormEvent) {
    e.preventDefault();
    setCreating(true);
    try {
      await apiClient.post("/users", createForm);
      queryClient.invalidateQueries({ queryKey: ["users"] });
      toast({ tone: "success", message: `Пользователь «${createForm.username}» создан` });
      setCreateForm({ username: "", email: "", password: "", role: "viewer" });
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось создать пользователя") });
    } finally {
      setCreating(false);
    }
  }

  async function changePassword(e: FormEvent) {
    e.preventDefault();
    setPwdSaving(true);
    try {
      await apiClient.post("/auth/change-password", pwdForm);
      toast({ tone: "success", message: "Пароль изменён" });
      setPwdForm({ current_password: "", new_password: "" });
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось изменить пароль") });
    } finally {
      setPwdSaving(false);
    }
  }

  return (
    <div className="animate-fade-in space-y-4">
      <PageHeader
        title="Пользователи"
        description="Роли и второй фактор. Свою роль изменить нельзя, последнего активного администратора понизить тоже нельзя. Доменные пользователи появляются при первом входе с ролью по группам AD; роль, назначенная здесь, важнее групп — чтобы вернуть роль по группам, выберите её снова."
      />
      <div className="table-shell">
        <table className="table-base">
          <thead>
            <tr>
              <th>Пользователь</th>
              <th>Вход</th>
              <th>Email</th>
              <th>Роль</th>
              <th>TOTP</th>
              <th>Статус</th>
            </tr>
          </thead>
          <tbody>
            {(users.data ?? []).map((u) => {
              const self = u.id === me?.id;
              const domain = u.auth_source === "ldap";
              return (
                <tr key={u.id}>
                  <td className="font-medium text-foreground">
                    {u.username}
                    {self && <span className="ml-1 text-xs font-normal text-subtle">(вы)</span>}
                    {u.display_name && <div className="text-xs font-normal text-subtle">{u.display_name}</div>}
                  </td>
                  <td className="text-muted-foreground">{domain ? "домен" : "локальный"}</td>
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
                    {domain && u.ldap_role && (
                      <div className="mt-1 text-xs text-subtle">
                        {u.role_override
                          ? `вручную · по группам AD: ${roleLabel(u.ldap_role)}`
                          : "по группам AD"}
                      </div>
                    )}
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

      <div className="grid gap-4 lg:grid-cols-2">
        {isAdmin && (
          <div className="surface-card p-5">
            <div className="mb-4 flex items-center gap-2">
              <UserPlus className="h-4 w-4 text-blue-600 dark:text-blue-400" />
              <h2 className="text-base font-semibold text-foreground">Создать пользователя</h2>
            </div>
            <form onSubmit={createUser} className="space-y-3">
              <div>
                <label htmlFor="new-username" className="field-label">Имя пользователя</label>
                <input id="new-username" type="text" autoComplete="off" value={createForm.username} onChange={(e) => setCreateForm({ ...createForm, username: e.target.value })} required minLength={3} className="input-base" />
              </div>
              <div>
                <label htmlFor="new-email" className="field-label">Email</label>
                <input id="new-email" type="email" autoComplete="off" value={createForm.email} onChange={(e) => setCreateForm({ ...createForm, email: e.target.value })} required className="input-base" />
              </div>
              <div>
                <label htmlFor="new-password" className="field-label">Пароль</label>
                <PasswordInput id="new-password" value={createForm.password} onChange={(v) => setCreateForm({ ...createForm, password: v })} autoComplete="new-password" />
                <p className="mt-1 text-xs text-subtle">Минимум 8 символов</p>
              </div>
              <div>
                <label htmlFor="new-role" className="field-label">Роль</label>
                <select id="new-role" value={createForm.role} onChange={(e) => setCreateForm({ ...createForm, role: e.target.value as UserRole })} className="input-base">
                  {ROLE_OPTIONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                </select>
              </div>
              <Button type="submit" loading={creating} className="w-full">Создать пользователя</Button>
            </form>
          </div>
        )}

        {domainSelf ? (
          <div className="surface-card p-5">
            <div className="mb-2 flex items-center gap-2">
              <KeyRound className="h-4 w-4 text-blue-600 dark:text-blue-400" />
              <h2 className="text-base font-semibold text-foreground">Пароль</h2>
            </div>
            <p className="text-sm text-muted-foreground">Вы вошли доменной учётной записью: пароль меняется в Windows (Ctrl+Alt+Del → «Изменить пароль»).</p>
          </div>
        ) : (
        <div className="surface-card p-5">
          <div className="mb-4 flex items-center gap-2">
            <KeyRound className="h-4 w-4 text-blue-600 dark:text-blue-400" />
            <h2 className="text-base font-semibold text-foreground">Смена своего пароля</h2>
          </div>
          <form onSubmit={changePassword} className="space-y-3">
            <div>
              <label htmlFor="cur-password" className="field-label">Текущий пароль</label>
              <PasswordInput id="cur-password" value={pwdForm.current_password} onChange={(v) => setPwdForm({ ...pwdForm, current_password: v })} autoComplete="current-password" minLength={1} />
            </div>
            <div>
              <label htmlFor="chg-password" className="field-label">Новый пароль</label>
              <PasswordInput id="chg-password" value={pwdForm.new_password} onChange={(v) => setPwdForm({ ...pwdForm, new_password: v })} autoComplete="new-password" />
              <p className="mt-1 text-xs text-subtle">Минимум 8 символов</p>
            </div>
            <Button type="submit" loading={pwdSaving} className="w-full">Изменить пароль</Button>
          </form>
        </div>
        )}
      </div>
    </div>
  );
}
