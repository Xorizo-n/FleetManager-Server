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
  created_at: string;
  updated_at: string;
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

export type TaskType = "playbook" | "software_scan" | "host_diagnostic" | "agent_version_scan" | "agent_update";
export type TaskStatus = "queued" | "running" | "success" | "failed";

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
}

export interface TaskRunDetail extends TaskRun {
  log_output: string | null;
  extra_vars: Record<string, unknown> | null;
}

export interface Repo {
  id: string;
  name: string;
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
