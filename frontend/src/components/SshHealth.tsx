import type { Host } from "../api/types";
import { relativeTime } from "../lib/format";

const REPAIRED: Record<string, string> = {
  start_type: "вернул автозапуск sshd",
  started: "запустил sshd",
  restarted: "перезапустил зависший sshd",
  firewall_rule: "восстановил правило брандмауэра",
  path: "восстановил System32 в PATH",
  default_shell: "вернул PowerShell оболочкой SSH",
  domain_trust: "восстановил доверие с доменом (nltest /sc_reset)",
};

const SHUTDOWN: Record<string, string> = {
  clean: "штатное выключение",
  restart: "перезагрузка",
  power_loss: "выключен кнопкой питания или обесточен",
  crash: "сбой Windows",
  unknown: "не определено",
};

const TRUST: Record<string, string> = {
  ok: "в порядке",
  broken: "нарушено",
  unreachable: "нет связи с контроллером домена",
};

/** Загрузка и прошлое завершение работы: «выключили» отличается от «пропал на ходу» */
function PowerLine({ host }: { host: Host }) {
  const power = host.power_state;
  if (!power?.booted_at) return null;
  const previous = power.previous_shutdown ? SHUTDOWN[power.previous_shutdown] ?? power.previous_shutdown : null;
  return (
    <p className="text-xs text-subtle">
      Загружен {relativeTime(power.booted_at)}
      {previous && (
        <>
          ; до этого — {previous}
          {power.previous_shutdown_at && <> ({relativeTime(power.previous_shutdown_at)})</>}
        </>
      )}
      {power.updates_installing && <>. Ставит обновления Windows — задачи ждут</>}
      {power.reboot_pending && !power.updates_installing && <>. Ждёт перезагрузки после обновлений</>}
    </p>
  );
}

/** SSH по отчёту агента: что мешает серверу зайти на ПК и что агент уже исправил сам */
export function SshHealthSection({ host }: { host: Host }) {
  const state = host.ssh_state;
  if (!state) {
    return <p className="text-sm text-subtle">Агент не присылает состояние SSH — его собирает агент с версии 2026.10.24</p>;
  }
  const problems = host.ssh_problems ?? [];
  const repaired = (state.repaired ?? []).map((r) => REPAIRED[r] ?? r);
  return (
    <div className="space-y-2 text-sm">
      {problems.length === 0 ? (
        <p className="text-emerald-700 dark:text-emerald-400">Препятствий для входа по SSH агент не видит</p>
      ) : (
        <ul className="list-disc space-y-1 pl-5 text-rose-600 dark:text-rose-400">
          {problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
      {repaired.length > 0 && <p className="text-muted-foreground">При последней проверке агент сам {repaired.join(", ")}</p>}
      <p className="text-xs text-subtle">
        {state.domain_trust && <>Доверие с доменом: {TRUST[state.domain_trust] ?? state.domain_trust}. </>}
        {state.host_keys?.length ? "Ключи хоста сверяются с присланными агентом. " : ""}
        Отчёт {relativeTime(state.reported_at ?? null)}
        {host.agent_update_target && <>. Ждёт самообновления до {host.agent_update_target}</>}
      </p>
      <PowerLine host={host} />
    </div>
  );
}
