import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Download, RefreshCw, Trash2 } from "lucide-react";
import { apiClient } from "../../api/client";
import { keys, useAgentVersions, useInstallers } from "../../api/queries";
import { useAuth } from "../../context/AuthContext";
import PageHeader from "../../components/ui/PageHeader";
import Button from "../../components/ui/Button";
import Checkbox from "../../components/ui/Checkbox";
import { Empty, ErrorText, Loading } from "../../components/ui/States";
import { useToast } from "../../components/ui/Toast";
import { downloadFromApi } from "../../lib/download";
import { apiError, formatDateTime, pcCount } from "../../lib/format";

interface EnrollmentToken {
  id: string;
  name: string;
  expires_at: string | null;
  is_active: boolean;
  created_at: string;
  installer_available: boolean;
}

const AGENT_INSTALLER = /^FleetManagerAgent-Setup(?:[-_].+)?\.exe$/i;

/** Всё про агента в одном месте: версия установщика, синхронизация с GitHub и токены регистрации. */
export default function Agent() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const queryClient = useQueryClient();
  const toast = useToast();
  const versions = useAgentVersions();
  const installers = useInstallers();
  const [syncing, setSyncing] = useState(false);
  const installer = installers.data?.find((f) => AGENT_INSTALLER.test(f.name));
  const v = versions.data;

  async function sync() {
    setSyncing(true);
    try {
      const { data } = await apiClient.post<{ updated: boolean; version?: string; reason?: string }>("/installers/agent/sync");
      toast({ tone: "success", message: data.updated ? `Установщик обновлён до ${data.version}` : data.reason || "Обновлений нет" });
      if (data.updated) {
        queryClient.invalidateQueries({ queryKey: keys.installers });
        queryClient.invalidateQueries({ queryKey: keys.agentVersions });
      }
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось проверить обновление агента") });
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div className="animate-fade-in space-y-6">
      <PageHeader title="Агент и токены" description="Установщик агента, версии на ПК и токены для регистрации новых ПК" />

      <section className="surface-panel space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-foreground">Установщик агента</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Сервер сам подтягивает свежий установщик из GitHub Releases. Обновление на ПК запускается со страницы «Хосты».
            </p>
          </div>
          <div className="flex gap-2">
            <Button size="sm" variant="secondary" onClick={sync} loading={syncing}>
              {!syncing && <RefreshCw className="h-3.5 w-3.5" />}
              Проверить обновление
            </Button>
            <Button size="sm" variant="secondary" disabled={!installer} onClick={() => installer && downloadFromApi(`/installers/${encodeURIComponent(installer.name)}/download`, installer.name)}>
              <Download className="h-3.5 w-3.5" />
              Скачать
            </Button>
          </div>
        </div>
        {versions.isLoading ? (
          <Loading />
        ) : (
          <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Stat label="Версия на сервере" value={<span className="font-mono">{v?.available_version ?? "—"}</span>} hint={installer ? `обновлён ${formatDateTime(installer.mtime)}` : "установщик не найден"} />
            <Stat label="Актуальная версия" value={pcCount(v?.up_to_date ?? 0)} to="/hosts?agent=up_to_date" tone="text-emerald-600 dark:text-emerald-400" />
            <Stat label="Устаревшая версия" value={pcCount(v?.outdated ?? 0)} to="/hosts?agent=outdated" tone="text-amber-600 dark:text-amber-400" />
            <Stat label="Версия неизвестна" value={pcCount(v?.unknown ?? 0)} to="/hosts?agent=unknown" />
          </dl>
        )}
      </section>

      {isAdmin ? <EnrollmentTokens /> : <p className="text-sm text-muted-foreground">Токены регистрации доступны администраторам.</p>}
    </div>
  );
}

function Stat({ label, value, hint, to, tone = "text-foreground" }: { label: string; value: React.ReactNode; hint?: string; to?: string; tone?: string }) {
  const body = (
    <>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={`mt-1 text-lg font-semibold ${tone}`}>{value}</dd>
      {hint && <dd className="text-xs text-subtle">{hint}</dd>}
    </>
  );
  return to ? (
    <Link to={to} className="rounded-lg border border-border px-3 py-2 hover:border-blue-500/40">{body}</Link>
  ) : (
    <div className="rounded-lg border border-border px-3 py-2">{body}</div>
  );
}

function EnrollmentTokens() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const tokens = useQuery({ queryKey: ["enrollment-tokens"], queryFn: () => apiClient.get<EnrollmentToken[]>("/agent/enrollment-tokens").then((r) => r.data) });
  const [name, setName] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [created, setCreated] = useState<string | null>(null);
  const [showRevoked, setShowRevoked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const all = tokens.data ?? [];
  const revoked = all.filter((t) => !t.is_active).length;
  const list = all.filter((t) => showRevoked || t.is_active);

  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data } = await apiClient.post<EnrollmentToken & { raw_token: string }>("/agent/enrollment-tokens", {
        name: name.trim(),
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
      });
      setCreated(data.raw_token);
      setName("");
      setExpiresAt("");
      queryClient.invalidateQueries({ queryKey: ["enrollment-tokens"] });
    } catch (err) {
      setError(apiError(err, "Не удалось создать токен"));
    } finally {
      setBusy(false);
    }
  }

  async function revoke(token: EnrollmentToken) {
    if (!window.confirm(`Отозвать токен «${token.name}»? Новые ПК с ним больше не зарегистрируются; уже зарегистрированные продолжат работать.`)) return;
    try {
      await apiClient.delete(`/agent/enrollment-tokens/${token.id}`);
      queryClient.invalidateQueries({ queryKey: ["enrollment-tokens"] });
      toast({ tone: "success", message: `Токен отозван: ${token.name}` });
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось отозвать токен") });
    }
  }

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-foreground">Токены регистрации</h2>
          <p className="mt-1 text-sm text-muted-foreground">Многоразовые токены, с которыми агент сам добавляет ПК в реестр. Установщик можно скачать с уже вшитым токеном.</p>
        </div>
        {revoked > 0 && (
          <label className="flex cursor-pointer items-center gap-2 text-sm text-muted-foreground">
            <Checkbox checked={showRevoked} onChange={(e) => setShowRevoked(e.target.checked)} />
            Показать отозванные ({revoked})
          </label>
        )}
      </div>

      <form onSubmit={create} className="surface-panel grid gap-3 md:grid-cols-[1.3fr_1fr_auto] md:items-end">
        <div>
          <label className="field-label" htmlFor="token-name">Название</label>
          <input id="token-name" className="input-base" required value={name} onChange={(e) => setName(e.target.value)} placeholder="Например, Учебный корпус" autoComplete="off" />
        </div>
        <div>
          <label className="field-label" htmlFor="token-exp">Действует до (необязательно)</label>
          <input id="token-exp" className="input-base" type="datetime-local" value={expiresAt} onChange={(e) => setExpiresAt(e.target.value)} />
        </div>
        <Button type="submit" loading={busy}>Создать токен</Button>
        <ErrorText>{error}</ErrorText>
      </form>

      {created && (
        <div className="surface-panel border-blue-500/40 bg-blue-500/5">
          <p className="text-sm font-medium">Токен создан. Скопируйте его сейчас — сервер хранит только хэш.</p>
          <div className="mt-3 flex gap-2">
            <code className="min-w-0 flex-1 break-all rounded-lg bg-background px-3 py-2 text-xs">{created}</code>
            <button type="button" className="btn-secondary btn-sm" onClick={() => navigator.clipboard.writeText(created).then(() => toast({ tone: "success", message: "Скопировано" }))} aria-label="Скопировать токен">
              <Copy className="h-4 w-4" />
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
              <th>Создан</th>
              <th>Статус</th>
              <th className="w-24" />
            </tr>
          </thead>
          <tbody>
            {list.map((t) => (
              <tr key={t.id} className={t.is_active ? "" : "opacity-60"}>
                <td className="font-medium text-foreground">{t.name}</td>
                <td className="text-muted-foreground">{t.expires_at ? formatDateTime(t.expires_at) : "без срока"}</td>
                <td className="text-muted-foreground">{formatDateTime(t.created_at)}</td>
                <td>{t.is_active ? <span className="text-emerald-600 dark:text-emerald-400">активен</span> : <span className="text-muted-foreground">отозван</span>}</td>
                <td className="text-right">
                  <div className="inline-flex gap-1">
                    {t.is_active && t.installer_available && (
                      <button
                        className="action-icon"
                        title="Скачать установщик с вшитым токеном"
                        aria-label={`Скачать установщик для ${t.name}`}
                        onClick={() => downloadFromApi(`/agent/enrollment-tokens/${t.id}/installer`, `FleetManagerAgent-${t.name}.exe`).catch(() => toast({ tone: "error", message: "Не удалось скачать установщик" }))}
                      >
                        <Download className="h-4 w-4" />
                      </button>
                    )}
                    {t.is_active && (
                      <button className="action-danger" onClick={() => revoke(t)} aria-label={`Отозвать ${t.name}`} title="Отозвать">
                        <Trash2 className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {tokens.isLoading && <Loading />}
        {!tokens.isLoading && list.length === 0 && <Empty>Активных токенов нет</Empty>}
      </div>
    </section>
  );
}
