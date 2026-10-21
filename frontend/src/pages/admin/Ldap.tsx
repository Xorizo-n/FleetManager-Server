import { FormEvent, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Plus, Search, X, XCircle } from "lucide-react";
import { apiClient } from "../../api/client";
import { UserRole } from "../../context/AuthContext";
import PageHeader from "../../components/ui/PageHeader";
import Button from "../../components/ui/Button";
import Switch from "../../components/ui/Switch";
import { ErrorText, Loading } from "../../components/ui/States";
import { useToast } from "../../components/ui/Toast";
import { apiError, formatDateTime } from "../../lib/format";

type GroupField = "admin_groups" | "operator_groups" | "viewer_groups";

interface LdapSettings {
  enabled: boolean;
  url: string;
  domain: string;
  base_dn: string;
  bind_dn: string;
  has_bind_password: boolean;
  admin_groups: string[];
  operator_groups: string[];
  viewer_groups: string[];
  source: "env" | "db";
  updated_at: string | null;
}

interface CheckReport {
  ok: boolean;
  error?: string;
  bind?: string;
  groups?: { dn: string; role: UserRole; found: boolean; members: number | null }[];
  user?: { username: string; found: boolean; ambiguous?: boolean; matched_by?: string | null; display_name?: string | null; role?: UserRole | null } | null;
}

interface FoundGroup {
  dn: string;
  name: string;
  description: string | null;
}

const ROLES: { field: GroupField; role: UserRole; label: string; hint: string }[] = [
  { field: "admin_groups", role: "admin", label: "Администраторы", hint: "всё, включая пользователей и эти настройки" },
  { field: "operator_groups", role: "operator", label: "Операторы", hint: "запуск плейбуков, управление хостами" },
  { field: "viewer_groups", role: "viewer", label: "Наблюдатели", hint: "только просмотр" },
];
const ROLE_LABEL: Record<UserRole, string> = { admin: "администратор", operator: "оператор", viewer: "наблюдатель", monitoring: "мониторинг" };
const MEMBER_LIMIT = 1000;

/** CN группы из DN: «CN=IRITRTF OOD Staff,OU=…» → «IRITRTF OOD Staff». */
const groupName = (dn: string) => dn.match(/^CN=((?:\\,|[^,])+)/i)?.[1].replace(/\\,/g, ",") ?? dn;

function GroupPicker({ form, password, onAdd }: { form: LdapSettings; password: string | null; onAdd: (dn: string) => void }) {
  const [query, setQuery] = useState("");
  const [manual, setManual] = useState("");
  const [found, setFound] = useState<FoundGroup[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);

  // Поиск внутри формы страницы: вложенный <form> по Enter отправил бы всю страницу
  const onEnter = (action: () => void) => (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      action();
    }
  };
  const addManual = () => {
    if (manual.includes("=")) onAdd(manual.trim());
    setManual("");
  };

  async function search() {
    if (query.trim().length < 2) return;
    setSearching(true);
    setError(null);
    try {
      const { data } = await apiClient.post<FoundGroup[]>("/settings/ldap/groups", { ...form, bind_password: password, query });
      setFound(data);
    } catch (err) {
      setError(apiError(err, "Не удалось найти группы"));
      setFound(null);
    } finally {
      setSearching(false);
    }
  }

  return (
    <div className="space-y-2 rounded-lg border border-border p-3">
      <div className="flex gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onEnter(search)}
          autoFocus
          placeholder="Поиск группы в домене: OOD Staff, ИРИТ-РТФ…"
          minLength={2}
          className="input-base py-1.5"
          aria-label="Поиск группы"
        />
        <Button size="sm" variant="secondary" type="button" onClick={search} loading={searching} disabled={query.trim().length < 2}>
          {!searching && <Search className="h-3.5 w-3.5" />}
          Найти
        </Button>
      </div>
      {error && <ErrorText>{error}</ErrorText>}
      {found && found.length === 0 && <p className="text-xs text-subtle">Ничего не нашлось</p>}
      {found && found.length > 0 && (
        <ul className="max-h-56 divide-y divide-border overflow-y-auto rounded-md border border-border">
          {found.map((g) => (
            <li key={g.dn}>
              <button
                type="button"
                onClick={() => onAdd(g.dn)}
                className="flex w-full items-start gap-2 px-3 py-2 text-left text-sm hover:bg-muted"
                title={g.dn}
              >
                <Plus className="mt-0.5 h-3.5 w-3.5 shrink-0 text-blue-600 dark:text-blue-400" />
                <span>
                  <span className="font-medium text-foreground">{g.name}</span>
                  {g.description && <span className="block text-xs text-subtle">{g.description}</span>}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex gap-2">
        <input
          value={manual}
          onChange={(e) => setManual(e.target.value)}
          onKeyDown={onEnter(addManual)}
          placeholder="или DN целиком: CN=…,OU=…,DC=at,DC=urfu,DC=ru"
          className="input-base py-1.5 font-mono text-xs"
          aria-label="DN группы"
        />
        <Button size="sm" variant="ghost" type="button" onClick={addManual} disabled={!manual.includes("=")}>
          Добавить
        </Button>
      </div>
    </div>
  );
}

export default function Ldap() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const saved = useQuery({ queryKey: ["ldap-settings"], queryFn: () => apiClient.get<LdapSettings>("/settings/ldap").then((r) => r.data) });
  const [form, setForm] = useState<LdapSettings | null>(null);
  // null — оставить сохранённый пароль, "" — удалить
  const [password, setPassword] = useState<string | null>(null);
  const [picker, setPicker] = useState<GroupField | null>(null);
  const [checkUser, setCheckUser] = useState("");
  const [report, setReport] = useState<CheckReport | null>(null);
  const [checking, setChecking] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (saved.data && form === null) setForm(saved.data);
  }, [saved.data, form]);

  if (saved.isLoading || !form) return saved.error ? <ErrorText>{apiError(saved.error, "Не удалось загрузить настройки")}</ErrorText> : <Loading />;

  const set = (patch: Partial<LdapSettings>) => {
    setForm({ ...form, ...patch });
    setReport(null);
  };
  const addGroup = (field: GroupField, dn: string) => {
    if (!form[field].some((g) => g.toLowerCase() === dn.toLowerCase())) set({ [field]: [...form[field], dn] });
  };
  const noGroups = ROLES.every((r) => form[r.field].length === 0);
  const hasPassword = password === null ? form.has_bind_password : password !== "";
  const dirty = password !== null || JSON.stringify(form) !== JSON.stringify(saved.data);

  async function check() {
    setChecking(true);
    try {
      const { data } = await apiClient.post<CheckReport>("/settings/ldap/check", { ...form, bind_password: password, username: checkUser || null });
      setReport(data);
    } catch (err) {
      setReport({ ok: false, error: apiError(err, "Проверка не удалась") });
    } finally {
      setChecking(false);
    }
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const { data } = await apiClient.put<LdapSettings>("/settings/ldap", { ...form, bind_password: password });
      queryClient.setQueryData(["ldap-settings"], data);
      setForm(data);
      setPassword(null);
      toast({ tone: "success", message: "Настройки входа через домен сохранены" });
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось сохранить настройки") });
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={save} className="animate-fade-in space-y-6">
      <PageHeader
        title="Вход через домен"
        description="Учётные записи Active Directory входят в Fleet Manager со своим паролем Windows. Доступ и роль по умолчанию задают группы AD; роль конкретного пользователя можно изменить на странице «Пользователи»."
      />

      <section className="surface-panel space-y-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-foreground">Вход доменной учётной записью</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {form.source === "env"
                ? "Сейчас действуют значения из .env на сервере. После сохранения здесь действуют эти настройки."
                : `Сохранено ${saved.data?.updated_at ? formatDateTime(saved.data.updated_at) : ""}. Локальные учётные записи работают всегда.`}
            </p>
          </div>
          <Switch checked={form.enabled} onChange={(enabled) => set({ enabled })} label="Вход через домен" />
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          <div>
            <label htmlFor="ldap-url" className="field-label">Контроллеры домена</label>
            <input id="ldap-url" value={form.url} onChange={(e) => set({ url: e.target.value })} required className="input-base font-mono text-xs" />
            <p className="mt-1 text-xs text-subtle">ldaps://, несколько через запятую</p>
          </div>
          <div>
            <label htmlFor="ldap-domain" className="field-label">Домен</label>
            <input id="ldap-domain" value={form.domain} onChange={(e) => set({ domain: e.target.value })} required className="input-base" />
          </div>
          <div>
            <label htmlFor="ldap-base" className="field-label">Корень поиска (base DN)</label>
            <input id="ldap-base" value={form.base_dn} onChange={(e) => set({ base_dn: e.target.value })} required className="input-base font-mono text-xs" />
          </div>
        </div>
      </section>

      <section className="surface-panel space-y-4">
        <div>
          <h2 className="text-sm font-semibold text-foreground">Служебная учётная запись</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Нужна для поиска групп на этой странице и для перепроверки доступа: с ней отключённый в домене или исключённый из групп
            пользователь теряет доступ в течение 15 минут, без неё — когда истечёт его сессия (до 7 дней). Достаточно прав на чтение.
          </p>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <div>
            <label htmlFor="ldap-bind" className="field-label">Логин</label>
            <input id="ldap-bind" value={form.bind_dn} onChange={(e) => set({ bind_dn: e.target.value })} placeholder="svc@at.urfu.ru" autoComplete="off" className="input-base" />
          </div>
          <div>
            <label htmlFor="ldap-password" className="field-label">Пароль</label>
            <div className="flex gap-2">
              <input
                id="ldap-password"
                type="password"
                autoComplete="new-password"
                value={password ?? ""}
                onChange={(e) => {
                  setPassword(e.target.value);
                  setReport(null);
                }}
                placeholder={form.has_bind_password ? "сохранён — введите, чтобы заменить" : "не задан"}
                className="input-base"
              />
              {form.has_bind_password && password !== "" && (
                <Button size="sm" variant="ghost" type="button" onClick={() => setPassword("")} title="Удалить сохранённый пароль">
                  Удалить
                </Button>
              )}
              {password !== null && (
                <Button size="sm" variant="ghost" type="button" onClick={() => setPassword(null)} title="Вернуть сохранённый">
                  Отменить
                </Button>
              )}
            </div>
            <p className="mt-1 text-xs text-subtle">Хранится зашифрованным и не показывается.{password === "" && form.has_bind_password && " Будет удалён при сохранении."}</p>
          </div>
        </div>
      </section>

      <section className="surface-panel space-y-4">
        <div>
          <h2 className="text-sm font-semibold text-foreground">Группы доступа</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Войти могут только участники этих групп (вложенные группы учитываются). Если пользователь в нескольких, действует старшая роль.
          </p>
        </div>
        {ROLES.map((r) => (
          <div key={r.field} className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <div>
                <span className="text-sm font-medium text-foreground">{r.label}</span>
                <span className="ml-2 text-xs text-subtle">{r.hint}</span>
              </div>
              <Button size="sm" variant="ghost" type="button" onClick={() => setPicker(picker === r.field ? null : r.field)}>
                <Plus className="h-3.5 w-3.5" />
                Добавить группу
              </Button>
            </div>
            {form[r.field].length === 0 ? (
              <p className="text-xs text-subtle">Нет групп</p>
            ) : (
              <ul className="flex flex-wrap gap-2">
                {form[r.field].map((dn) => (
                  <li key={dn} className="inline-flex items-center gap-1 rounded-full bg-muted py-1 pl-3 pr-1 text-sm" title={dn}>
                    {groupName(dn)}
                    <button
                      type="button"
                      onClick={() => set({ [r.field]: form[r.field].filter((g) => g !== dn) })}
                      className="rounded-full p-0.5 text-subtle hover:bg-background hover:text-foreground"
                      aria-label={`Убрать ${groupName(dn)}`}
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {picker === r.field && (
              <GroupPicker
                form={form}
                password={password}
                onAdd={(dn) => {
                  addGroup(r.field, dn);
                  setPicker(null);
                }}
              />
            )}
          </div>
        ))}
        {form.enabled && noGroups && <p className="text-sm text-amber-600 dark:text-amber-400">Без групп через домен не войдёт никто — добавьте хотя бы одну.</p>}
      </section>

      <section className="surface-panel space-y-3">
        <div>
          <h2 className="text-sm font-semibold text-foreground">Проверка</h2>
          <p className="mt-1 text-sm text-muted-foreground">Проверяет настройки с этой страницы до сохранения: служебную запись, группы и роль пользователя. Пароль пользователя не нужен.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <input value={checkUser} onChange={(e) => setCheckUser(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); check(); } }} placeholder="Логин, почта или имя (необязательно)" className="input-base max-w-xs py-1.5" aria-label="Логин для проверки" />
          <Button size="sm" variant="secondary" type="button" onClick={check} loading={checking} disabled={!form.bind_dn || !hasPassword}>
            Проверить
          </Button>
        </div>
        {(!form.bind_dn || !hasPassword) && <p className="text-xs text-subtle">Для проверки нужна служебная учётная запись.</p>}
        {report && !report.ok && (
          <p className="flex items-center gap-2 text-sm text-rose-600 dark:text-rose-400"><XCircle className="h-4 w-4 shrink-0" />{report.error}</p>
        )}
        {report?.ok && (
          <ul className="space-y-1.5 text-sm">
            <li className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />Служебная учётная запись подключилась</li>
            {report.groups?.map((g) => (
              <li key={g.role + g.dn} className="flex items-center gap-2" title={g.dn}>
                {g.found ? <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" /> : <XCircle className="h-4 w-4 shrink-0 text-rose-600 dark:text-rose-400" />}
                <span>
                  {groupName(g.dn)} → {ROLE_LABEL[g.role]}:{" "}
                  {g.found ? `${g.members !== null && g.members >= MEMBER_LIMIT ? `${MEMBER_LIMIT}+` : g.members} уч. записей` : "группа не найдена"}
                </span>
              </li>
            ))}
            {report.user && (
              <li className="flex items-center gap-2">
                {report.user.role ? <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" /> : <XCircle className="h-4 w-4 shrink-0 text-rose-600 dark:text-rose-400" />}
                <span>
                  {!report.user.found
                    ? report.user.ambiguous
                      ? `${report.user.username}: под этим именем несколько записей — войти можно только логином Windows`
                      : `${report.user.username}: не найден в домене`
                    : report.user.role
                      ? `${report.user.display_name || report.user.username} (${report.user.username}) войдёт с ролью «${ROLE_LABEL[report.user.role]}»`
                      : `${report.user.display_name || report.user.username} (${report.user.username}): не войдёт — отключён или не входит в группы`}
                  {report.user.matched_by && <span className="ml-1 text-xs text-subtle">· найден как {report.user.matched_by}</span>}
                </span>
              </li>
            )}
          </ul>
        )}
      </section>

      <div className="flex justify-end gap-2">
        <Button
          variant="ghost"
          type="button"
          disabled={!dirty}
          onClick={() => {
            setForm(saved.data ?? null);
            setPassword(null);
            setReport(null);
          }}
        >
          Сбросить
        </Button>
        <Button type="submit" loading={saving} disabled={!dirty || (form.enabled && noGroups)}>
          Сохранить
        </Button>
      </div>
    </form>
  );
}
