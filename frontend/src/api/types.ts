// Типы ответов backend, общие для всех страниц.

export type HostStatus = "online" | "offline" | "unknown";
export type VersionStatus = "up_to_date" | "outdated" | "newer" | "unknown" | "no_agent";

export interface HostGroup {
  id: string;
  name: string;
  description: string | null;
  credential_id: string | null;
  // Корпус > этаж > аудитория: сервер раскладывает ПК по имени (SU5-D206-TEMP -> SU5-D206).
  parent_id: string | null;
  is_auto: boolean;
}

export interface Host {
  id: string;
  ip_address: string | null;
  hostname: string | null;
  group_id: string | null;
  os: string;
  status: HostStatus;
  last_checked_at: string | null;
  comment: string | null;
  credential_id: string | null;
  has_agent: boolean;
  agent_version: string | null;
  agent_version_checked_at: string | null;
  last_seen_at?: string | null;
  hw_manufacturer?: string | null;
  hw_model?: string | null;
  hw_serial_number?: string | null;
  hw_os_caption?: string | null;
  hw_processor?: string | null;
  hw_total_memory_bytes?: number | null;
  /** MAC адаптера, через который ПК пришёл на сервер, — для пробуждения по сети */
  hw_mac_address?: string | null;
  hw_network_adapters?: NetworkAdapter[] | null;
  /** Локальные диски из последнего heartbeat; у агентов до 2026.10.15 нет */
  hw_disks?: HostDisk[] | null;
  /** Активация Windows и Office от агента (с 2026.10.17), собирается раз в час */
  license_activation?: LicenseActivation | null;
  /** Худшее состояние продуктов вида; null — нет данных или продукт не установлен */
  activation_windows?: ActivationState | null;
  activation_office?: ActivationState | null;
  /** Состав рабочего места от агента (с 2026.10.17): плата, память, диски, видео, мониторы, периферия */
  hw_components?: HwComponents | null;
  /** Изменения периферии, ожидающие подтверждения (держатся меньше 30 минут) */
  hw_pending_devices?: PendingDevice[];
  /** Последняя запись в журнале оборудования */
  hw_changed_at?: string | null;
  /** Обои на ПК по отчёту агента (с 2026.10.18) */
  wallpaper_state?: WallpaperState | null;
  /** SSH по отчёту агента: sshd, брандмауэр, PATH, права входа (с 2026.10.25 — полностью) */
  ssh_state?: SshState | null;
  /** Причины, по которым сервер не попадёт на ПК по SSH, найденные в отчёте агента */
  ssh_problems?: string[];
  /** Версия, которую агент поставит сам, без SSH */
  agent_update_target?: string | null;
  created_at: string;
  updated_at: string;
}

export interface NetworkAdapter {
  name: string | null;
  description: string | null;
  mac_address: string | null;
  ipv4: string[];
  status: string | null;
  /** «802.3» — проводной */
  media_type: string | null;
  /** Скорость линка, бит/с; null — нет линка или старый агент */
  link_speed_bps?: number | null;
}

export type WallpaperKind = "desktop" | "lock_screen";

export interface CurrentWallpaper {
  path: string;
  sha256: string | null;
  /** policy — локальная политика, csp — PersonalizationCSP, user — собственные обои пользователя */
  source: string | null;
}

export interface WallpaperState {
  desktop: CurrentWallpaper | null;
  lock_screen: CurrentWallpaper | null;
  applied_desktop_id: string | null;
  applied_lock_screen_id: string | null;
  error: string | null;
  reported_at: string;
}

export interface Wallpaper {
  id: string;
  name: string;
  original_name: string | null;
  content_type: string;
  sha256: string;
  size_bytes: number;
  width: number;
  height: number;
  created_at: string;
  thumbnail_base64: string;
  /** Перцептивный хэш миниатюры: у вариантов одной картинки почти совпадает */
  phash: string | null;
}

export interface ObservedWallpaper {
  sha256: string;
  path: string | null;
  thumbnail_base64: string;
  phash: string | null;
}

export interface WallpaperAssignment {
  id: string;
  host_id: string | null;
  group_id: string | null;
  kind: WallpaperKind;
  wallpaper_id: string;
  updated_at: string;
}

export interface WallpaperSchedule {
  id: string;
  apply_at: string;
  host_ids: string[];
  group_ids: string[];
  /** id обоев, "clear" — снять назначение, null — не менять */
  desktop: string | null;
  lock_screen: string | null;
  comment: string | null;
  status: "pending" | "applied" | "cancelled" | "failed";
  result: string | null;
  created_at: string;
  applied_at: string | null;
  created_by_name: string | null;
}

export interface HwComponents {
  baseboard: { manufacturer: string | null; product: string | null; serial_number: string | null } | null;
  bios_version: string | null;
  memory_modules: { slot: string | null; manufacturer: string | null; part_number: string | null; serial_number: string | null; capacity_bytes: number | null; speed_mhz: number | null }[];
  physical_disks: { model: string | null; serial_number: string | null; bus_type: string | null; size_bytes: number | null }[];
  gpus: { name: string | null; driver_version: string | null; pnp_id: string | null }[];
  /** connection — VideoOutputTechnology: 0 VGA, 4 DVI, 5 HDMI, 10 DisplayPort, 2147483648 встроенная панель */
  monitors: { manufacturer: string | null; model: string | null; serial_number: string | null; product_code: string | null; year: number | null; connection: number | null }[];
  input_devices: Peripheral[];
  usb_devices: Peripheral[];
}

export interface Peripheral {
  kind: "keyboard" | "mouse" | "usb";
  name: string | null;
  vid: string | null;
  pid: string | null;
  serial: string | null;
  device_class: string | null;
}

export type DeviceCategory = "system" | "baseboard" | "bios" | "memory" | "disk" | "gpu" | "monitor" | "keyboard" | "mouse" | "usb";

export interface PendingDevice {
  category: DeviceCategory;
  item: Record<string, unknown>;
  /** true — устройство пропало, false — появилось новое */
  missing: boolean;
  since: string;
}

export interface HardwareEvent {
  id: string;
  host_id: string;
  hostname: string | null;
  category: DeviceCategory;
  action: "added" | "removed" | "changed";
  summary: string;
  details: Record<string, unknown> | null;
  created_at: string;
}

/** licensed — активирован; expiring — KMS давно не продлевал, до истечения < 30 дней; grace — пробный период; unlicensed — не активирован */
export type ActivationState = "licensed" | "expiring" | "grace" | "unlicensed";

export interface LicenseActivation {
  collected_at: string | null;
  /** CMID: одинаковый у клонов образа без sysprep /generalize */
  client_machine_id: string | null;
  /** Открыт ли с ПК порт KMS */
  kms_probe: { host: string; port: number; reachable: boolean; error: string | null } | null;
  products: LicenseProduct[];
}

export interface LicenseProduct {
  kind: "windows" | "office";
  id: string | null;
  name: string | null;
  description: string | null;
  /** «Volume:GVLK», «Retail», «MAK»… */
  channel: string | null;
  partial_product_key: string | null;
  /** 0 — нет лицензии, 1 — активирован, 2–4 и 6 — пробный период, 5 — уведомления */
  license_status: number;
  /** HRESULT причины (LicenseStatusReason) */
  status_reason: number | null;
  /** До конца пробного периода или до истечения KMS-активации, минут */
  grace_minutes: number | null;
  kms_machine: string | null;
  kms_port: number | null;
  discovered_kms_machine: string | null;
  discovered_kms_port: number | null;
  /** Последнее обращение к KMS из журнала; result — HRESULT, null — ответа нет */
  last_request: { at: string; kms: string | null; result: string | null } | null;
}

export interface HostDisk {
  /** «C:» */
  name: string;
  label: string | null;
  file_system: string | null;
  size_bytes: number;
  free_bytes: number;
}

export interface AgentHostVersion {
  host_id: string;
  hostname: string | null;
  agent_version: string | null;
  version_status: VersionStatus;
  agent_version_checked_at: string | null;
}

export interface AgentVersionOverview {
  available_version: string | null;
  installer_present: boolean;
  total_agents: number;
  up_to_date: number;
  outdated: number;
  unknown: number;
  hosts: AgentHostVersion[];
}

export interface Credential {
  id: string;
  name: string;
  type: "ssh_key" | "password" | "token";
  login: string | null;
  created_at: string;
  is_agent_managed?: boolean;
  host_count?: number;
  group_count?: number;
  repo_count?: number;
}

export type TaskType = "playbook" | "software_scan" | "host_diagnostic" | "agent_version_scan" | "agent_update" | "access_change" | "host_wake";
// Статус запуска — сводка по его ПК: waiting — кто-то ждёт включения, pending — следующий плейбук
// цепочки ждёт предыдущий (after_task_id). released — у старых ожидающих задач (до запусков)
export type TaskStatus = "queued" | "running" | "success" | "failed" | "waiting" | "cancelled" | "pending" | "released";

/** Состояние ПК в запуске (backend/services/waiting_tasks.py); ready — появился, ждёт пачку */
export type HostState = "waiting" | "ready" | "pending" | "queued" | "running" | "success" | "failed" | "cancelled";

export interface TaskRun {
  id: string;
  task_type: TaskType;
  playbook_name: string | null;
  host_ids: string[];
  status: TaskStatus;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  created_by?: string | null;
  created_by_name?: string | null;
  /** От чьего имени выполнялся плейбук (backend/services/run_as.py) */
  run_as?: RunAs | null;
  repo_id?: string | null;
  /** Запуск на много ПК: сам не выполняется, выполняют дочерние задачи (runs) */
  grouped?: boolean | null;
  /** Состояние каждого ПК; у выполняющей задачи — её итог по ПК */
  host_states?: Record<string, HostState> | null;
  /** Выполняющая задача запуска */
  parent_id?: string | null;
  /** Следующий плейбук цепочки: стартует после этой задачи */
  after_task_id?: string | null;
  /** Ответ на запуск: сколько ПК ждут появления в сети */
  waiting_hosts?: number;
}

export interface RunAs {
  /** Под кем пробовали войти; null — инициатора нет, причина в reason */
  login: string | null;
  reason: string | null;
  as_user: string[];
  /** host_id → почему на этом ПК осталась учётка установки агента */
  fallback: Record<string, string>;
}

export interface TaskRunDetail extends TaskRun {
  log_output: string | null;
  extra_vars: Record<string, unknown> | null;
  /** Выполняющие задачи запуска: сразу для ПК в сети и по одной на пачку появившихся */
  runs: TaskRun[];
  /** Плейбуки одной цепочки по порядку; у одиночного запуска пусто */
  chain: { id: string; playbook_name: string | null; status: TaskStatus }[];
}

export interface Repo {
  id: string;
  name: string;
  /** "local" — плейбуки из редактора Fleet Manager, хранятся только на сервере */
  kind?: "git" | "local";
  git_url: string;
  branch: string;
  credential_id: string | null;
}

export interface PlaybookFile {
  name: string;
  path: string;
  display_name?: string | null;
}

export interface Schedule {
  id: string;
  repo_id: string;
  playbook_name: string;
  host_group_id: string | null;
  host_group_ids: string[];
  host_ids: string[];
  extra_vars: Record<string, string>;
  cron_expression: string;
  enabled: boolean;
  created_at: string;
  next_run_at: string | null;
  /** Владелец — создал или последним изменил: плейбук идёт от его имени */
  owner_id?: string | null;
  owner_name?: string | null;
  owner_domain?: boolean;
}

export interface SoftwareItem {
  id: string;
  host_id: string;
  name: string;
  version: string | null;
  install_method: string;
  status: string;
  detected_at: string;
}

export interface SoftwarePackage {
  name: string;
  host_count: number;
  versions: { version: string | null; host_count: number }[];
}

export interface InstallerFile {
  name: string;
  size: number;
  mtime: string;
}

export interface AlertSummary {
  days: number;
  total: number;
  hosts: number;
  by_host: { host_id: string; count: number; last_at: string }[];
}

export interface AgentAlert {
  id: string;
  host_id: string;
  alert_type: string;
  message: string;
  created_at: string;
}

// Цели запуска: целиком выбранные группы (раскрываются на сервере вместе с
// подгруппами) плюс отдельные ПК.
export interface HostSelection {
  groupIds: string[];
  hostIds: string[];
}

export interface SshState {
  installed?: boolean | null;
  start_type?: string | null;
  listening?: boolean | null;
  responding?: boolean | null;
  repaired?: string[];
  firewall_rule?: string | null;
  domain_trust?: string | null;
  login_is_admin?: boolean | null;
  path_ok?: boolean | null;
  host_keys?: string[];
  reported_at?: string;
}
