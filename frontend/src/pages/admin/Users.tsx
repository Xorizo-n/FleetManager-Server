import { FormEvent, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2, UserPlus } from "lucide-react";
import { apiClient } from "../../api/client";
import { CurrentUser, UserRole, useAuth } from "../../context/AuthContext";
import PageHeader from "../../components/ui/PageHeader";
import Badge from "../../components/ui/Badge";
import Button from "../../components/ui/Button";
import Modal from "../../components/ui/Modal";
import PasswordInput from "../../components/ui/PasswordInput";
import { Empty, Loading } from "../../components/ui/States";
import { useToast } from "../../components/ui/Toast";
import { apiError, plural } from "../../lib/format";

const ROLE_OPTIONS: { value: UserRole; label: string; hint: string }[] = [
  { value: "admin", label: "Администратор", hint: "всё, включая пользователей и учётные данные" },
  { value: "operator", label: "Оператор", hint: "запуск плейбуков, управление хостами" },
  { value: "viewer", label: "Наблюдатель", hint: "только просмотр" },
  { value: "monitoring", label: "Мониторинг", hint: "дашборд мониторинга с алертами и звуком" },
];

const roleLabel = (role: UserRole) => ROLE_OPTIONS.find((r) => r.value === role)?.label ?? role;

export default function Users() {
  const { user: me } = useAuth();
  const queryClient = useQueryClient();
  const toast = useToast();
  const users = useQuery({ queryKey: ["users"], queryFn: () => apiClient.get<CurrentUser[]>("/users").then((r) => r.data) });

  const isAdmin = me?.role === "admin";
  const [createOpen, setCreateOpen] = useState(false);
  const [deleting, setDeleting] = useState<CurrentUser | null>(null);
  const activeAdmins = (users.data ?? []).filter((u) => u.role === "admin" && u.is_active).length;

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

  /** Почему эту запись нельзя удалить; null — можно */
  function deleteBlocked(u: CurrentUser): string | null {
    if (u.id === me?.id) return "Свою учётную запись удалить нельзя";
    if (u.role === "admin" && u.is_active && activeAdmins <= 1) return "Последнего активного администратора удалить нельзя";
    return null;
  }

  return (
    <div className="animate-fade-in space-y-4">
      <PageHeader
        title="Пользователи"
        description="Роли и второй фактор. Свою роль изменить нельзя, последнего активного администратора понизить тоже нельзя. Доменные пользователи появляются при первом входе с ролью по группам AD; роль, назначенная здесь, важнее групп — чтобы вернуть роль по группам, выберите её снова."
        actions={
          isAdmin && (
            <Button onClick={() => setCreateOpen(true)}>
              <UserPlus className="h-4 w-4" />
              Создать пользователя
            </Button>
          )
        }
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
              {isAdmin && <th className="w-12"><span className="sr-only">Действия</span></th>}
            </tr>
          </thead>
          <tbody>
            {(users.data ?? []).map((u) => {
              const self = u.id === me?.id;
              const domain = u.auth_source === "ldap";
              const blocked = deleteBlocked(u);
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
                  {isAdmin && (
                    <td className="text-right">
                      <button
                        onClick={() => setDeleting(u)}
                        disabled={!!blocked}
                        title={blocked ?? `Удалить ${u.username}`}
                        aria-label={`Удалить ${u.username}`}
                        className="action-danger disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent"
                      >
                        <Trash2 className="h-4 w-4" aria-hidden="true" />
                      </button>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
        {users.isLoading && <Loading />}
        {users.data?.length === 0 && <Empty>Пользователей нет</Empty>}
      </div>

      <CreateUserModal open={createOpen} onClose={() => setCreateOpen(false)} />
      <DeleteUserModal target={deleting} onClose={() => setDeleting(null)} />
    </div>
  );
}

const EMPTY_FORM = { username: "", email: "", password: "", role: "viewer" as UserRole };

function CreateUserModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function close() {
    setForm(EMPTY_FORM);
    setError(null);
    onClose();
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await apiClient.post("/users", form);
      queryClient.invalidateQueries({ queryKey: ["users"] });
      toast({ tone: "success", message: `Пользователь «${form.username}» создан` });
      close();
    } catch (err) {
      setError(apiError(err, "Не удалось создать пользователя"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="Новый пользователь"
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={close}>Отмена</Button>
          <Button type="submit" form="create-user-form" loading={saving}>Создать</Button>
        </>
      }
    >
      <form id="create-user-form" onSubmit={submit} className="space-y-3">
        <p className="text-sm text-muted-foreground">
          Локальная учётная запись с паролем. Доменных пользователей создавать не нужно: они появляются сами при первом входе.
        </p>
        <div>
          <label htmlFor="new-username" className="field-label">Имя пользователя</label>
          <input id="new-username" type="text" autoComplete="off" autoFocus value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required minLength={3} className="input-base" />
        </div>
        <div>
          <label htmlFor="new-email" className="field-label">Email</label>
          <input id="new-email" type="email" autoComplete="off" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required className="input-base" />
        </div>
        <div>
          <label htmlFor="new-password" className="field-label">Пароль</label>
          <PasswordInput id="new-password" value={form.password} onChange={(v) => setForm({ ...form, password: v })} autoComplete="new-password" />
          <p className="mt-1 text-xs text-subtle">Минимум 8 символов</p>
        </div>
        <div>
          <label htmlFor="new-role" className="field-label">Роль</label>
          <select id="new-role" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as UserRole })} className="input-base">
            {ROLE_OPTIONS.map((r) => <option key={r.value} value={r.value}>{r.label} — {r.hint}</option>)}
          </select>
        </div>
        {error && <p className="text-sm text-rose-600 dark:text-rose-400" role="alert">{error}</p>}
      </form>
    </Modal>
  );
}

function DeleteUserModal({ target, onClose }: { target: CurrentUser | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [schedules, setSchedules] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSchedules(null);
    setError(null);
    if (!target) return;
    apiClient
      .get<{ schedules: number }>(`/users/${target.id}/usage`)
      .then((r) => setSchedules(r.data.schedules))
      .catch(() => setSchedules(null));
  }, [target]);

  async function remove() {
    if (!target) return;
    setSaving(true);
    setError(null);
    try {
      await apiClient.delete(`/users/${target.id}`);
      queryClient.invalidateQueries({ queryKey: ["users"] });
      toast({ tone: "success", message: `Пользователь «${target.username}» удалён` });
      onClose();
    } catch (err) {
      setError(apiError(err, "Не удалось удалить пользователя"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open={!!target}
      onClose={onClose}
      title="Удалить пользователя?"
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Отмена</Button>
          <Button variant="danger" onClick={remove} loading={saving}>Удалить</Button>
        </>
      }
    >
      {target && (
        <div className="space-y-3 text-sm text-muted-foreground">
          <p>
            Учётная запись <span className="font-medium text-foreground">{target.username}</span>
            {target.display_name ? ` (${target.display_name})` : ""} будет удалена, войти под ней будет нельзя.
            Задачи и записи журнала, созданные этим пользователем, останутся, но без автора.
          </p>
          {!!schedules && (
            <p className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-amber-700 dark:text-amber-300">
              {plural(schedules, "расписание плейбука выполнялось", "расписания плейбуков выполнялись", "расписаний плейбуков выполнялись")} от имени этого
              пользователя. Они продолжат работать, но от учётной записи установки агента.
            </p>
          )}
          {target.auth_source === "ldap" && (
            <p>
              Это доменная запись: если пользователь всё ещё в группах AD, при следующем входе она создастся снова. Чтобы закрыть доступ насовсем,
              уберите его из групп доступа в домене.
            </p>
          )}
          {error && <p className="text-rose-600 dark:text-rose-400" role="alert">{error}</p>}
        </div>
      )}
    </Modal>
  );
}
