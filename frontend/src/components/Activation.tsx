import type { ActivationState, Host, LicenseProduct } from "../api/types";
import Badge from "./ui/Badge";
import { formatDateTime, pcCount, relativeTime } from "../lib/format";
import {
  ACTIVATION_LABELS,
  ACTIVATION_TONES,
  channelLabel,
  describeHresult,
  formatGrace,
  isKmsClient,
  probeError,
  productState,
  productTitle,
} from "../lib/activation";

const DOT = { success: "bg-emerald-500", warning: "bg-amber-500", danger: "bg-rose-500" };
const TEXT = {
  success: "text-foreground/80",
  warning: "text-amber-700 dark:text-amber-300",
  danger: "text-rose-600 dark:text-rose-400",
};

function Chip({ label, state }: { label: string; state: ActivationState }) {
  const tone = ACTIVATION_TONES[state];
  return (
    <span className={`inline-flex items-center gap-1 ${TEXT[tone]}`}>
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${DOT[tone]}`} />
      {label}
    </span>
  );
}

/** Ячейка реестра: состояние Windows и Office, подробности — во всплывающей подсказке */
export function ActivationCell({ host }: { host: Host }) {
  const windows = host.activation_windows;
  const office = host.activation_office;
  if (!windows && !office) return <span className="text-xs text-muted-foreground">—</span>;
  const probe = host.license_activation?.kms_probe;
  const title = [
    windows && `Windows: ${ACTIVATION_LABELS[windows]}`,
    office && `Office: ${ACTIVATION_LABELS[office]}`,
    probe && `KMS ${probe.host}:${probe.port} ${probe.reachable ? "доступен" : `недоступен — ${probeError(probe.error)}`}`,
  ]
    .filter(Boolean)
    .join("\n");
  return (
    <span className="flex min-w-0 items-center gap-2 text-xs" title={title}>
      {windows && <Chip label="Win" state={windows} />}
      {office && <Chip label="Office" state={office} />}
    </span>
  );
}

/** Раздел карточки хоста: продукты, доступность KMS и CMID */
export function ActivationSection({ host, sameCmid }: { host: Host; sameCmid: number }) {
  const activation = host.license_activation;
  if (!activation) {
    return (
      <p className="text-sm text-subtle">
        {host.has_agent ? "Агент ещё не прислал данные об активации — их собирает агент с версии 2026.10.17" : "Данные об активации собирает агент"}
      </p>
    );
  }
  const probe = activation.kms_probe;
  const products = [...activation.products].sort((a, b) => Number(a.kind === "office") - Number(b.kind === "office"));
  return (
    <div className="space-y-2">
      {products.length === 0 ? (
        <p className="text-sm text-subtle">Продуктов Windows и Office с ключом не найдено</p>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {products.map((p, i) => (
            <ProductRow key={p.id ?? i} product={p} />
          ))}
        </ul>
      )}
      {probe && (
        <p className={`text-sm ${probe.reachable ? "text-muted-foreground" : "text-rose-600 dark:text-rose-400"}`}>
          KMS <span className="font-mono text-xs">{probe.host}:{probe.port}</span>{" "}
          {probe.reachable ? (
            "доступен с этого ПК"
          ) : (
            <>
              недоступен с этого ПК: {probeError(probe.error)}. Активация не пройдёт, пока сеть не пропускает TCP {probe.port} до KMS.
            </>
          )}
        </p>
      )}
      {activation.client_machine_id && (
        <p className="text-xs text-subtle">
          CMID <span className="font-mono">{activation.client_machine_id}</span>
          {sameCmid > 1 && (
            <>
              {" "}— такой же у {pcCount(sameCmid - 1)} в реестре: образ снят без sysprep /generalize, и KMS считает эти ПК одним компьютером. Пока
              у KMS хватает других клиентов, активации это не мешает.
            </>
          )}
        </p>
      )}
      <p className="text-xs text-subtle" title={formatDateTime(activation.collected_at)}>
        Агент проверяет активацию раз в час, последний раз — {relativeTime(activation.collected_at)}
      </p>
    </div>
  );
}

function ProductRow({ product: p }: { product: LicenseProduct }) {
  const state = productState(p);
  const channel = channelLabel(p);
  const grace = formatGrace(p.grace_minutes);
  const request = p.last_request;
  const requestFailed = !!request?.result && request.result !== "0x00000000";
  return (
    <li className="space-y-0.5 px-3 py-2 text-sm">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="min-w-0 flex-1 font-medium text-foreground">
          {productTitle(p)}
          <span className="font-normal text-xs text-muted-foreground">
            {channel && ` · ${channel}`}
            {p.partial_product_key && <span className="font-mono"> · …{p.partial_product_key}</span>}
          </span>
        </span>
        <Badge status={state} tone={ACTIVATION_TONES[state]}>
          {ACTIVATION_LABELS[state]}
          {grace && state !== "licensed" && `, ${state === "expiring" ? "осталось" : "ещё"} ${grace}`}
        </Badge>
      </div>
      {state === "licensed" && grace && isKmsClient(p) && (
        <p className="text-xs text-muted-foreground">KMS-активация действует ещё {grace}, продлевается раз в 7 дней</p>
      )}
      {state !== "licensed" && p.status_reason !== null && p.status_reason !== 0 && (
        <p className="text-xs text-muted-foreground">Причина: {describeHresult(p.status_reason)}</p>
      )}
      {request && (
        <p className={`text-xs ${requestFailed ? "text-rose-600 dark:text-rose-400" : "text-muted-foreground"}`} title={formatDateTime(request.at)}>
          Обращение к KMS{request.kms && <span className="font-mono"> {request.kms}</span>} {relativeTime(request.at)}
          {" — "}
          {request.result ? describeHresult(request.result) : "ответа нет в журнале"}
        </p>
      )}
    </li>
  );
}
