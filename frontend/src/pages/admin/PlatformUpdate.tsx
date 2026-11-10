import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../../api/client";
import PageHeader from "../../components/ui/PageHeader";
import Button from "../../components/ui/Button";
import { ErrorText, Loading } from "../../components/ui/States";
import { apiError, formatDateTime } from "../../lib/format";

type Event = { at: string; message: string };
type Operation = { id: string; version: string; status: string; message: string; started_at: string; backup_complete?: boolean; migration_started?: boolean; events: Event[] };
type Status = {
  current: { version: string; commit?: string };
  available?: { version: string; notes: string; published_at: string; url: string };
  checked_at?: string; check_error?: string; busy: boolean; maintenance: boolean;
  operation?: Operation; history: Operation[];
};

function isNewer(available: string, current: string) {
  if (current === "unversioned") return true;
  const next = available.slice(1).split(".").map(Number);
  const installed = current.slice(1).split(".").map(Number);
  for (let i = 0; i < 3; i++) {
    if (next[i] !== installed[i]) return next[i] > installed[i];
  }
  return false;
}

export default function PlatformUpdate() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [installing, setInstalling] = useState(false);
  const [confirmation, setConfirmation] = useState<"install" | "restore" | null>(null);
  const status = useQuery({
    queryKey: ["platform-update"],
    queryFn: () => apiClient.get<Status>("/settings/platform").then(r => r.data),
    refetchInterval: 5000,
    retry: false,
  });
  const data = status.data;
  const op = data?.operation;
  const active = data?.busy || busy;
  const disconnected = !!status.error && (installing || data?.busy || data?.maintenance);

  async function action(kind: "check" | "install" | "restore") {
    setBusy(true); setError(null); setConfirmation(null);
    try {
      await apiClient.post(`/settings/platform/${kind}`, kind === "install" ? { version: data?.available?.version } : kind === "restore" ? { confirm_data_loss: true } : {});
      if (kind !== "check") setInstalling(true);
      await status.refetch();
    } catch (err) {
      setError(apiError(err, "Не удалось выполнить операцию"));
    } finally { setBusy(false); }
  }

  return <div className="space-y-6">
    <PageHeader title="Обновление платформы" description="Проверка и установка стабильных версий FleetManager из GitHub." />
    {error && <ErrorText>{error}</ErrorText>}
    {disconnected ? <p role="status" className="rounded-xl border border-border p-4">Компоненты платформы перезапускаются. Связь восстановится автоматически; не запускайте установку повторно.</p> : status.error && <ErrorText>{apiError(status.error, "Служба обновлений недоступна")}</ErrorText>}
    {status.isLoading && <Loading />}
    {data && <>
      <section className="surface-card p-5 space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div><h2 className="text-lg font-semibold">Установленная версия</h2>
            <p>{data.current.version === "unversioned" ? "Установка до перехода на релизы" : data.current.version}</p>
            {data.current.commit && <p className="text-xs text-subtle">Сборка {data.current.commit.slice(0, 12)}</p>}
            <p className="text-sm text-subtle">Последняя проверка: {data.checked_at ? formatDateTime(data.checked_at) : "ещё не выполнялась"}</p>
          </div>
          <Button variant="secondary" disabled={active} onClick={() => action("check")}>Проверить обновления</Button>
        </div>
        {data.check_error && <ErrorText>{data.check_error}</ErrorText>}
        {data.available ? <div className="space-y-3 border-t border-border pt-4">
          <h2 className="text-lg font-semibold">Последний релиз: {data.available.version}</h2>
          <p className="text-sm text-subtle">{formatDateTime(data.available.published_at)}</p>
          <p className="whitespace-pre-wrap text-sm">{data.available.notes || "Описание изменений отсутствует."}</p>
          <a className="text-primary underline" href={data.available.url} target="_blank" rel="noopener noreferrer">Открыть релиз на GitHub</a>
          {isNewer(data.available.version, data.current.version) ? <div><Button disabled={active || data.maintenance} onClick={() => setConfirmation("install")}>Установить {data.available.version}</Button></div> : <p>Установлена актуальная или более новая версия.</p>}
        </div> : <p className="text-sm text-subtle">Готовых релизов пока нет либо проверка не завершилась.</p>}
      </section>
      {confirmation && <section role="alertdialog" aria-label="Подтверждение операции" className="surface-card p-5 space-y-4">
        <h2 className="font-semibold">{confirmation === "install" ? "Установить обновление?" : "Восстановить предыдущую версию?"}</h2>
        <p>{confirmation === "install" ? "Система дождётся завершения задач и создаст резервную копию. Во время установки интерфейс и связь с агентами будут временно недоступны." : "Текущая база данных будет заменена копией перед обновлением. Изменения после создания копии будут потеряны."}</p>
        <div className="flex gap-3"><Button variant={confirmation === "restore" ? "danger" : "primary"} disabled={active} onClick={() => action(confirmation)}>Подтвердить</Button><Button variant="secondary" onClick={() => setConfirmation(null)}>Отмена</Button></div>
      </section>}
      {op && <section className="surface-card p-5 space-y-3" aria-live="polite">
        <h2 className="text-lg font-semibold">Обновление до {op.version}</h2>
        <p>{op.message}</p>
        {op.status === "recovery_required" && <>
          <p>Если интерфейс недоступен, восстановление можно запустить из консоли сервера по инструкции эксплуатации.</p>
          {(op.backup_complete || !op.migration_started) && <Button variant="danger" disabled={active} onClick={() => setConfirmation("restore")}>Восстановить предыдущую версию</Button>}
        </>}
        <ol className="space-y-2 text-sm">{op.events.map((e, i) => <li key={i}><span className="text-subtle">{formatDateTime(e.at)}</span> — {e.message}</li>)}</ol>
      </section>}
      {!!data.history.length && <section className="surface-card p-5 space-y-3"><h2 className="text-lg font-semibold">История обновлений</h2>{data.history.map(run => <div key={run.id} className="border-t border-border pt-3"><p>{run.version} · {formatDateTime(run.started_at)}</p><p className="text-sm text-muted-foreground">{run.message}</p></div>)}</section>}
    </>}
  </div>;
}
