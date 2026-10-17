import type { ActivationState, Host, LicenseActivation, LicenseProduct } from "../api/types";

// Сводку по каждому ПК считает сервер (services/activation.py, activation_windows/office);
// здесь — подписи и состояние отдельного продукта для карточки хоста по тем же правилам.

export const ACTIVATION_LABELS: Record<ActivationState, string> = {
  licensed: "активирован",
  expiring: "истекает",
  grace: "пробный период",
  unlicensed: "не активирован",
};

export const ACTIVATION_TONES: Record<ActivationState, "success" | "warning" | "danger"> = {
  licensed: "success",
  expiring: "warning",
  grace: "warning",
  unlicensed: "danger",
};

const SEVERITY: Record<ActivationState, number> = { licensed: 0, expiring: 1, grace: 2, unlicensed: 3 };
const EXPIRING_MINUTES = 30 * 24 * 60;

export const isKmsClient = (p: LicenseProduct) =>
  (p.description ?? "").toUpperCase().includes("VOLUME_KMSCLIENT") || (p.channel ?? "").toLowerCase() === "volume:gvlk";

export function productState(p: LicenseProduct): ActivationState {
  if (p.license_status === 1) return isKmsClient(p) && !!p.grace_minutes && p.grace_minutes < EXPIRING_MINUTES ? "expiring" : "licensed";
  return [2, 3, 4, 6].includes(p.license_status) ? "grace" : "unlicensed";
}

/** Для сортировки: чем хуже активация Windows или Office, тем больше; -1 — нет данных */
export function activationSeverity(host: Host): number {
  const states = [host.activation_windows, host.activation_office].filter((s): s is ActivationState => !!s);
  return states.length ? Math.max(...states.map((s) => SEVERITY[s])) : -1;
}

/** Не активирован или в пробном периоде: «истекает» сюда не входит — пока он ещё активирован */
export const notActivated = (state: ActivationState | null | undefined) => state === "unlicensed" || state === "grace";

export const kmsUnreachable = (host: Host) => host.license_activation?.kms_probe?.reachable === false;

/** 38879 мин -> «27 дн.», 300 -> «5 ч» */
export function formatGrace(minutes: number | null | undefined): string | null {
  if (!minutes || minutes <= 0) return null;
  if (minutes >= 1440) return `${Math.floor(minutes / 1440)} дн.`;
  return minutes >= 60 ? `${Math.floor(minutes / 60)} ч` : `${minutes} мин`;
}

export const hresultHex = (code: number) => `0x${(code >>> 0).toString(16).toUpperCase().padStart(8, "0")}`;

// Коды, которые встречаются при KMS-активации: LicenseStatusReason продукта и итог обращения к KMS из журнала
const HRESULT_TEXT: Record<string, string> = {
  "0x00000000": "успешно",
  "0xC0020017": "KMS-сервер недоступен по сети",
  "0x800706BA": "KMS-сервер недоступен по сети",
  "0xC004F074": "не удалось связаться ни с одним KMS-сервером",
  "0x8007232B": "KMS-сервер не найден в DNS",
  "0x8007251D": "в DNS нет записи о KMS-сервере",
  "0x8007274C": "истекло время ожидания подключения к KMS",
  "0x8007274D": "KMS-сервер отклонил подключение",
  "0xC004F038": "у KMS недостаточно клиентов для активации",
  "0xC004F039": "у KMS недостаточно клиентов для активации",
  "0xC004F041": "KMS-сервер сам не активирован",
  "0xC004F042": "этот KMS-сервер не активирует данный продукт",
  "0xC004F06C": "время на ПК и KMS расходится больше чем на 4 часа",
  "0xC004F009": "пробный период истёк",
  "0xC004F00F": "привязка к оборудованию вышла за допуск (клонирование образа или замена оборудования)",
  "0x4004F00C": "работает в пробном периоде",
  "0xC004C003": "ключ заблокирован сервером активации",
  "0xC004F050": "недопустимый ключ продукта",
  "0x8007139F": "служба лицензирования в неподходящем состоянии",
  "0x80070005": "отказано в доступе",
};

export function describeHresult(code: string | number | null | undefined): string | null {
  if (code === null || code === undefined) return null;
  const hex = typeof code === "number" ? hresultHex(code) : code.toUpperCase().replace(/^0X/, "0x");
  const text = HRESULT_TEXT[hex];
  return text ? `${text} (${hex})` : `код ${hex}`;
}

const PROBE_ERRORS: Record<string, string> = {
  TimedOut: "нет ответа — порт закрыт фильтром или узел недоступен",
  ConnectionRefused: "подключение отклонено",
  HostNotFound: "имя не найдено в DNS",
  NetworkUnreachable: "нет маршрута до сети KMS",
  HostUnreachable: "нет маршрута до KMS",
};

export const probeError = (error: string | null) => (error ? PROBE_ERRORS[error] ?? error : "нет подключения");

/** «Windows(R), ProfessionalEducation edition» -> «Windows ProfessionalEducation», «Office 19, Office19ProPlus2019VL_KMS_Client_AE edition» -> «Office19ProPlus2019VL_KMS_Client_AE» */
export function productTitle(p: LicenseProduct): string {
  const name = (p.name ?? (p.kind === "windows" ? "Windows" : "Office")).replace(/\(R\)/g, "").replace(/\s+edition$/i, "").trim();
  return name.replace(/^Windows,\s*/, "Windows ").replace(/^Office \d+,\s*/, "");
}

/** Канал лицензии: KMS, MAK, Retail; Retail(Grace) — заглушка, которую Office ставит до ввода ключа */
export function channelLabel(p: LicenseProduct): string | null {
  const description = (p.description ?? "").toUpperCase();
  if (description.includes("VOLUME_KMSCLIENT")) return "KMS";
  if (description.includes("RETAIL(GRACE)") || /_Grace\b/i.test(p.name ?? "")) return "без ключа";
  if (description.includes("MAK")) return "MAK";
  if (description.includes("OEM")) return "OEM";
  if (description.includes("RETAIL")) return "Retail";
  return p.channel;
}

/** Сколько ПК в реестре с тем же CMID — признак клонов образа без sysprep /generalize */
export function sameCmidCount(activation: LicenseActivation | null | undefined, hosts: Host[]): number {
  const cmid = activation?.client_machine_id;
  if (!cmid) return 0;
  return hosts.filter((h) => h.license_activation?.client_machine_id === cmid).length;
}
