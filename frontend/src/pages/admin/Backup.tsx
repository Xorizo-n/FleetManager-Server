import { FormEvent, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Database, FolderArchive, KeyRound, Play, ShieldCheck, XCircle } from "lucide-react";
import { apiClient } from "../../api/client";
import PageHeader from "../../components/ui/PageHeader";
import Button from "../../components/ui/Button";
import Switch from "../../components/ui/Switch";
import { Empty, ErrorText, Loading } from "../../components/ui/States";
import { useToast } from "../../components/ui/Toast";
import { apiError, formatDateTime } from "../../lib/format";

type Kind = "db" | "share" | "check";

interface BackupRun {
  id: string;
  kind: Kind;
  started_at: string;
  finished_at: string | null;
  ok: boolean | null;
  message: string | null;
  bytes_added: number | null;
  details: Record<string, any> | null;
}

interface BackupSettings {
  enabled: boolean;
  sftp_host: string;
  sftp_port: number;
  sftp_user: string;
  sftp_path: string;
  has_sftp_password: boolean;
  has_repo_password: boolean;
  host_key_fingerprint: string | null;
  initialized: boolean;
  updated_at: string | null;
  last_ok: Record<Kind, string | null>;
  runs: BackupRun[];
}

interface Snapshot {
  id: string;
  time: string;
  tags: string[];
  paths: string[];
  bytes: number | null;
}

interface CheckResult {
  ok: boolean;
  error?: string;
  repository?: "exists" | "missing" | null;
  host_key_fingerprint?: string | null;
  host_key_pinned?: boolean;
}

const KINDS: { kind: Kind; title: string; when: string; what: string; icon: JSX.Element }[] = [
  { kind: "db", title: "БД и конфигурация", when: "каждые 4 часа", what: "дамп БД, .env с ключом шифрования учётных данных, сертификаты, локальные плейбуки", icon: <Database className="h-4 w-4" /> },
  { kind: "share", title: "Хранилище установщиков", when: "каждую ночь в 02:30", what: "/mnt/soft-share: установщики и обои; передаются только изменения", icon: <FolderArchive className="h-4 w-4" /> },
  { kind: "check", title: "Проверка восстановления", when: "по воскресеньям в 05:00", what: "целостность копий, восстановление дампа во временную БД и расшифровка учётных данных ключом из копии", icon: <ShieldCheck className="h-4 w-4" /> },
];
const KIND_LABEL: Record<Kind, string> = { db: "БД", share: "soft-share", check: "проверка" };

const bytes = (n: number | null | undefined) =>
  n == null ? "—" : n >= 1e9 ? `${(n / 1e9).toFixed(1).replace(".", ",")} ГБ` : n >= 1e6 ? `${Math.round(n / 1e6)} МБ` : `${Math.round(n / 1e3)} КБ`;

function runSummary(run: BackupRun): string {
  if (run.ok === null) return run.finished_at ? "—" : "идёт…";
  if (!run.ok) return run.message ?? "ошибка";
  const d = run.details ?? {};
  if (run.kind === "check") {
    const r = d.restored ?? {};
    return `восстановлено: ${r.hosts ?? "?"} хостов, ${r.credentials ?? "?"} учётных данных${d.credentials_decrypted ? ", ключ подходит" : ""} · хранилище ${bytes(d.repository_bytes)}`;
  }
  return `передано ${bytes(run.bytes_added)}${d.repository_created ? " · хранилище создано" : ""}`;
}

function PasswordField({ id, label, saved, value, onChange, hint, locked }: {
  id: string; label: string; saved: boolean; value: string | null; onChange: (v: string | null) => void; hint?: string; locked?: string;
}) {
  return (
    <div>
      <label htmlFor={id} className="field-label">{label}</label>
      <div className="flex gap-2">
        <input
          id={id}
          type="password"
          autoComplete="new-password"
          value={value ?? ""}
          disabled={!!locked}
          onChange={(e) => onChange(e.target.value)}
          placeholder={locked ? "задан" : saved ? "сохранён — введите, чтобы заменить" : "не задан"}
          className="input-base"
        />
        {value !== null && !locked && (
          <Button size="sm" variant="ghost" type="button" onClick={() => onChange(null)}>Отменить</Button>
        )}
      </div>
      <p className="mt-1 text-xs text-subtle">{locked ?? hint}</p>
    </div>
  );
}

export default function Backup() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const saved = useQuery({
    queryKey: ["backup-settings"],
    queryFn: () => apiClient.get<BackupSettings>("/settings/backup").then((r) => r.data),
    // Пока что-то копируется — обновлять журнал
    refetchInterval: (q) => ((q.state.data?.runs ?? []).some((r) => !r.finished_at) ? 5000 : 60000),
  });
  const snapshots = useQuery({
    queryKey: ["backup-snapshots"],
    queryFn: () => apiClient.get<Snapshot[]>("/settings/backup/snapshots").then((r) => r.data),
    enabled: !!saved.data?.initialized,
    staleTime: 60000,
  });
  const [form, setForm] = useState<Pick<BackupSettings, "enabled" | "sftp_host" | "sftp_port" | "sftp_user" | "sftp_path"> | null>(null);
  const [sftpPassword, setSftpPassword] = useState<string | null>(null);
  const [repoPassword, setRepoPassword] = useState<string | null>(null);
  const [repoConfirm, setRepoConfirm] = useState("");
  const [check, setCheck] = useState<CheckResult | null>(null);
  const [busy, setBusy] = useState<"check" | "save" | Kind | null>(null);

  useEffect(() => {
    if (saved.data && form === null) {
      const { enabled, sftp_host, sftp_port, sftp_user, sftp_path } = saved.data;
      setForm({ enabled, sftp_host, sftp_port, sftp_user, sftp_path });
    }
  }, [saved.data, form]);

  if (saved.isLoading || !form || !saved.data) return saved.error ? <ErrorText>{apiError(saved.error, "Не удалось загрузить настройки")}</ErrorText> : <Loading />;
  const s = saved.data;
  const set = (patch: Partial<typeof form>) => {
    setForm({ ...form, ...patch });
    setCheck(null);
  };
  const body = () => ({ ...form, sftp_password: sftpPassword, repo_password: repoPassword });
  const repoMismatch = repoPassword !== null && repoPassword !== "" && repoPassword !== repoConfirm;
  const dirty = sftpPassword !== null || repoPassword !== null ||
    JSON.stringify(form) !== JSON.stringify({ enabled: s.enabled, sftp_host: s.sftp_host, sftp_port: s.sftp_port, sftp_user: s.sftp_user, sftp_path: s.sftp_path });
  const runningKinds = new Set(s.runs.filter((r) => !r.finished_at).map((r) => r.kind));

  async function runCheck() {
    setBusy("check");
    try {
      setCheck((await apiClient.post<CheckResult>("/settings/backup/check", body())).data);
    } catch (err) {
      setCheck({ ok: false, error: apiError(err, "Проверка не удалась") });
    } finally {
      setBusy(null);
    }
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    if (repoMismatch) return;
    setBusy("save");
    try {
      const { data } = await apiClient.put<BackupSettings>("/settings/backup", body());
      queryClient.setQueryData(["backup-settings"], data);
      setForm({ enabled: data.enabled, sftp_host: data.sftp_host, sftp_port: data.sftp_port, sftp_user: data.sftp_user, sftp_path: data.sftp_path });
      setSftpPassword(null);
      setRepoPassword(null);
      setRepoConfirm("");
      toast({ tone: "success", message: `Настройки сохранены · ключ хранилища ${data.host_key_fingerprint ?? "—"}` });
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось сохранить настройки") });
    } finally {
      setBusy(null);
    }
  }

  async function runNow(kind: Kind) {
    setBusy(kind);
    try {
      await apiClient.post("/settings/backup/run", { kind });
      await queryClient.invalidateQueries({ queryKey: ["backup-settings"] });
      toast({ tone: "info", message: "Запущено — ход виден в журнале ниже" });
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось запустить") });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="animate-fade-in space-y-6">
      <PageHeader
        title="Резервные копии"
        description="Копии вне этой ВМ: без БД и .env сервера доступ ко всем ПК теряется — агенты не узнают сервер, а SSH-ключи ПК не расшифровать. Копии зашифрованы restic и уходят в хранилище по SFTP."
      />

      <section className="grid gap-3 md:grid-cols-3">
        {KINDS.map((k) => {
          const last = s.last_ok[k.kind];
          const lastRun = s.runs.find((r) => r.kind === k.kind && r.finished_at);
          const failed = lastRun?.ok === false;
          return (
            <div key={k.kind} className="surface-panel flex flex-col gap-2">
              <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <span className="text-blue-600 dark:text-blue-400">{k.icon}</span>
                {k.title}
              </div>
              <p className="text-xs text-muted-foreground">{k.when}: {k.what}</p>
              <p className={`flex items-center gap-1.5 text-sm ${failed ? "text-rose-600 dark:text-rose-400" : last ? "text-emerald-600 dark:text-emerald-400" : "text-muted-foreground"}`}>
                {failed ? <XCircle className="h-4 w-4 shrink-0" /> : last ? <CheckCircle2 className="h-4 w-4 shrink-0" /> : null}
                {failed ? `Ошибка: ${lastRun?.message ?? "—"}` : last ? `Последняя удачная: ${formatDateTime(last)}` : "Ещё не выполнялась"}
              </p>
              <div className="mt-auto">
                <Button size="sm" variant="secondary" onClick={() => runNow(k.kind)} loading={busy === k.kind || runningKinds.has(k.kind)} disabled={!s.has_repo_password || !!busy || runningKinds.has(k.kind)}>
                  {!(busy === k.kind || runningKinds.has(k.kind)) && <Play className="h-3.5 w-3.5" />}
                  {runningKinds.has(k.kind) ? "Идёт…" : "Запустить сейчас"}
                </Button>
              </div>
            </div>
          );
        })}
      </section>

      <form onSubmit={save} className="surface-panel space-y-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-foreground">Хранилище</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              SFTP-сервер вне этой ВМ. Ключ SSH сервера закрепляется при сохранении: если он сменится, копирование остановится с ошибкой.
              {s.host_key_fingerprint && <> Ключ: <span className="font-mono text-xs text-foreground">{s.host_key_fingerprint}</span>.</>}
            </p>
          </div>
          <Switch checked={form.enabled} onChange={(enabled) => set({ enabled })} label="Копирование по расписанию" />
        </div>
        <div className="grid gap-3 md:grid-cols-[2fr_1fr_2fr_3fr]">
          <div>
            <label htmlFor="b-host" className="field-label">Сервер</label>
            <input id="b-host" value={form.sftp_host} onChange={(e) => set({ sftp_host: e.target.value })} placeholder="10.152.240.10" className="input-base font-mono" />
          </div>
          <div>
            <label htmlFor="b-port" className="field-label">Порт</label>
            <input id="b-port" type="number" min={1} max={65535} value={form.sftp_port} onChange={(e) => set({ sftp_port: Number(e.target.value) || 22 })} className="input-base font-mono" />
          </div>
          <div>
            <label htmlFor="b-user" className="field-label">Логин</label>
            <input id="b-user" value={form.sftp_user} onChange={(e) => set({ sftp_user: e.target.value })} placeholder="backupuser" autoComplete="off" className="input-base" />
          </div>
          <div>
            <label htmlFor="b-path" className="field-label">Каталог</label>
            <input id="b-path" value={form.sftp_path} onChange={(e) => set({ sftp_path: e.target.value })} placeholder="/srv/backup/fleet-manager" className="input-base font-mono" />
          </div>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <PasswordField id="b-sftp-pass" label="Пароль SFTP" saved={s.has_sftp_password} value={sftpPassword} onChange={(v) => { setSftpPassword(v); setCheck(null); }}
            hint="Хранится зашифрованным и не показывается." />
          <div className="space-y-2">
            <PasswordField id="b-repo-pass" label="Пароль шифрования копий" saved={s.has_repo_password} value={repoPassword} onChange={(v) => { setRepoPassword(v); setCheck(null); }}
              locked={s.initialized ? "Задан при создании хранилища и не меняется здесь." : undefined}
              hint="Не короче 12 символов." />
            {repoPassword !== null && repoPassword !== "" && (
              <input type="password" autoComplete="new-password" value={repoConfirm} onChange={(e) => setRepoConfirm(e.target.value)} placeholder="ещё раз" aria-label="Повтор пароля шифрования" className="input-base" />
            )}
            {repoMismatch && repoConfirm && <p className="text-xs text-rose-600 dark:text-rose-400">Пароли не совпадают</p>}
          </div>
        </div>
        <p className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-sm text-amber-700 dark:text-amber-300">
          <KeyRound className="mt-0.5 h-4 w-4 shrink-0" />
          Сохраните пароль шифрования копий и пароль SFTP вне этого сервера — в менеджере паролей или в сейфе. При потере ВМ только они открывают копии: здесь они пропадут вместе с ВМ.
        </p>
        {check && (
          <div className={`flex items-start gap-2 text-sm ${check.ok ? "text-emerald-700 dark:text-emerald-400" : "text-rose-700 dark:text-rose-300"}`} role="status">
            {check.ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0" />}
            <span>
              {check.ok
                ? `Вход по SFTP и каталог в порядке. ${check.repository === "exists" ? "Хранилище restic уже есть, пароль шифрования подходит." : check.repository === "missing" ? "Хранилище restic будет создано при первом копировании." : "Пароль шифрования не задан — проверен только вход."}`
                : check.error}
              {check.host_key_fingerprint && (
                <span className="block text-xs text-muted-foreground">
                  Ключ сервера {check.host_key_fingerprint}{check.host_key_pinned ? " (закреплён)" : " — будет закреплён при сохранении; сверьте его с сервером"}
                </span>
              )}
            </span>
          </div>
        )}
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="secondary" type="button" onClick={runCheck} loading={busy === "check"} disabled={!!busy}>Проверить</Button>
          <Button type="submit" loading={busy === "save"} disabled={!dirty || !!busy || repoMismatch}>Сохранить</Button>
        </div>
      </form>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-foreground">Журнал</h2>
        <div className="table-shell">
          <table className="table-base">
            <thead>
              <tr>
                <th>Начало</th>
                <th>Что</th>
                <th>Длительность</th>
                <th>Итог</th>
              </tr>
            </thead>
            <tbody>
              {s.runs.map((r) => (
                <tr key={r.id}>
                  <td className="whitespace-nowrap text-muted-foreground">{formatDateTime(r.started_at)}</td>
                  <td>{KIND_LABEL[r.kind] ?? r.kind}</td>
                  <td className="whitespace-nowrap tabular-nums text-muted-foreground">
                    {r.finished_at ? `${Math.max(1, Math.round((new Date(r.finished_at).getTime() - new Date(r.started_at).getTime()) / 1000))} с` : "…"}
                  </td>
                  <td className={r.ok === false ? "text-rose-600 dark:text-rose-400" : r.ok ? "text-foreground" : "text-muted-foreground"}>{runSummary(r)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {s.runs.length === 0 && <Empty>Копирований ещё не было</Empty>}
        </div>
      </section>

      {s.initialized && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold text-foreground">Что лежит в хранилище</h2>
          {snapshots.isLoading && <Loading />}
          {snapshots.error && <ErrorText>{apiError(snapshots.error, "Хранилище не ответило")}</ErrorText>}
          {snapshots.data && (
            <div className="table-shell">
              <table className="table-base">
                <thead>
                  <tr>
                    <th>Снимок</th>
                    <th>Время</th>
                    <th>Вид</th>
                    <th>Объём</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshots.data.map((snap) => (
                    <tr key={snap.id}>
                      <td className="font-mono text-xs">{snap.id}</td>
                      <td className="text-muted-foreground">{formatDateTime(snap.time)}</td>
                      <td>{snap.tags.join(", ")}</td>
                      <td className="tabular-nums text-muted-foreground">{bytes(snap.bytes)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {snapshots.data.length === 0 && <Empty>Снимков пока нет</Empty>}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
