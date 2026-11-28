import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronDown, KeyRound, LogOut, Moon, Sun } from "lucide-react";
import { apiClient } from "../api/client";
import { UserRole, useAuth } from "../context/AuthContext";
import { useTheme } from "../context/ThemeContext";
import { apiError } from "../lib/format";
import Button from "./ui/Button";
import Modal from "./ui/Modal";
import Menu from "./ui/Menu";
import PasswordInput from "./ui/PasswordInput";
import { useToast } from "./ui/Toast";

export const ROLE_LABELS: Record<UserRole, string> = { admin: "админ", operator: "оператор", viewer: "наблюдатель", monitoring: "мониторинг" };

/** Мини-профиль в шапке: кто вошёл, тема, смена пароля (локальная запись) и выход */
export default function UserMenu() {
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const navigate = useNavigate();
  const [passwordOpen, setPasswordOpen] = useState(false);

  if (!user) return null;
  const domain = user.auth_source === "ldap";

  function handleLogout() {
    logout();
    navigate("/login");
  }

  return (
    <>
      <Menu
        trigger={({ id, open, toggle }) => (
          <button
            id={id}
            type="button"
            onClick={toggle}
            aria-haspopup="menu"
            aria-expanded={open}
            aria-label={`Профиль ${user.username}`}
            className="flex items-center gap-2 rounded-lg px-1.5 py-1 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-blue-600 text-xs font-semibold text-white">
              {user.username.slice(0, 1).toUpperCase()}
            </span>
            <span className="hidden max-w-[140px] truncate sm:inline">{user.username}</span>
            <ChevronDown aria-hidden="true" className={`hidden h-3.5 w-3.5 transition-transform sm:block ${open ? "rotate-180" : ""}`} />
          </button>
        )}
        header={
          <div className="w-[min(18rem,calc(100vw-5rem))] border-b border-border px-3 pb-3 pt-2">
            <p className="truncate text-sm font-medium text-foreground">{user.display_name || user.username}</p>
            {user.display_name && <p className="truncate text-xs text-muted-foreground">{user.username}</p>}
            <p className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
              <span className="rounded-md bg-muted px-1.5 py-0.5">{ROLE_LABELS[user.role]}</span>
              <span>{domain ? "доменная учётная запись" : "локальная учётная запись"}</span>
            </p>
            {domain && (
              <p className="mt-2 flex gap-2.5 text-xs text-subtle">
                <KeyRound className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                Пароль доменной записи меняется в Windows: Ctrl+Alt+Del → «Изменить пароль»
              </p>
            )}
          </div>
        }
        items={[
          { id: "theme", label: theme === "dark" ? "Светлая тема" : "Тёмная тема",
            icon: theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />,
            onClick: toggleTheme, keepOpen: true },
          ...(domain ? [] : [{ label: "Сменить пароль", icon: <KeyRound className="h-4 w-4" />, onClick: () => setPasswordOpen(true) }]),
          "divider",
          { label: "Выйти", icon: <LogOut className="h-4 w-4" />, danger: true, onClick: handleLogout },
        ]}
      />

      <ChangePasswordModal open={passwordOpen} onClose={() => setPasswordOpen(false)} />
    </>
  );
}

function ChangePasswordModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast();
  const [form, setForm] = useState({ current_password: "", new_password: "", repeat: "" });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function close() {
    setForm({ current_password: "", new_password: "", repeat: "" });
    setError(null);
    onClose();
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (form.new_password !== form.repeat) {
      setError("Новые пароли не совпадают");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await apiClient.post("/auth/change-password", { current_password: form.current_password, new_password: form.new_password });
      toast({ tone: "success", message: "Пароль изменён" });
      close();
    } catch (err) {
      setError(apiError(err, "Не удалось изменить пароль"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="Смена пароля"
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={close}>Отмена</Button>
          <Button type="submit" form="change-password-form" loading={saving}>Изменить пароль</Button>
        </>
      }
    >
      <form id="change-password-form" onSubmit={submit} className="space-y-3">
        <div>
          <label htmlFor="cur-password" className="field-label">Текущий пароль</label>
          <PasswordInput id="cur-password" value={form.current_password} onChange={(v) => setForm({ ...form, current_password: v })} autoComplete="current-password" minLength={1} dialogAutoFocus />
        </div>
        <div>
          <label htmlFor="chg-password" className="field-label">Новый пароль</label>
          <PasswordInput id="chg-password" value={form.new_password} onChange={(v) => setForm({ ...form, new_password: v })} autoComplete="new-password" />
          <p className="mt-1 text-xs text-subtle">Минимум 8 символов</p>
        </div>
        <div>
          <label htmlFor="rep-password" className="field-label">Новый пароль ещё раз</label>
          <PasswordInput id="rep-password" value={form.repeat} onChange={(v) => setForm({ ...form, repeat: v })} autoComplete="new-password" />
        </div>
        {error && <p className="text-sm text-rose-600 dark:text-rose-400" role="alert">{error}</p>}
      </form>
    </Modal>
  );
}
