import { useMemo } from "react";
import { QueryClient, useQuery } from "@tanstack/react-query";
import { apiClient } from "./client";
import type {
  AgentAlert,
  AlertSummary,
  AgentVersionOverview,
  Credential,
  Host,
  HostGroup,
  InstallerFile,
  PlaybookFile,
  Repo,
  Schedule,
  SoftwareItem,
  SoftwarePackage,
  TaskRun,
  TaskRunDetail,
  VersionStatus,
} from "./types";
import { buildGroupTree } from "../lib/groupTree";
import { useAuth } from "../context/AuthContext";

// Общий кэш данных: хосты и группы грузятся один раз и переиспользуются всеми
// страницами, после действий кэш инвалидируется по ключу.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, refetchOnWindowFocus: false, retry: 1 },
  },
});

export const keys = {
  hosts: ["hosts"] as const,
  groups: ["groups"] as const,
  agentVersions: ["agent-versions"] as const,
  credentials: ["credentials"] as const,
  tasks: (params: Record<string, unknown>) => ["tasks", params] as const,
  task: (id: string) => ["task", id] as const,
  repos: ["repos"] as const,
  files: (repoId: string) => ["playbook-files", repoId] as const,
  schedules: ["schedules"] as const,
  packages: (params: Record<string, unknown>) => ["software-packages", params] as const,
  hostSoftware: (hostId: string) => ["host-software", hostId] as const,
  packageHosts: (name: string) => ["package-hosts", name] as const,
  installers: ["installers"] as const,
  alerts: (hostId?: string) => ["alerts", hostId ?? "all"] as const,
};

const get = <T,>(url: string, params?: Record<string, unknown>) => apiClient.get<T>(url, { params }).then((r) => r.data);

export const useHosts = () => useQuery({ queryKey: keys.hosts, queryFn: () => get<Host[]>("/hosts") });
export const useGroups = () => useQuery({ queryKey: keys.groups, queryFn: () => get<HostGroup[]>("/hosts/groups") });
export const useAgentVersions = () =>
  useQuery({ queryKey: keys.agentVersions, queryFn: () => get<AgentVersionOverview>("/agent/versions") });

export function useCanEdit() {
  const { user } = useAuth();
  return user?.role === "admin" || user?.role === "operator";
}

export function useCredentials() {
  const canEdit = useCanEdit();
  return useQuery({ queryKey: keys.credentials, queryFn: () => get<Credential[]>("/credentials"), enabled: canEdit });
}

/** Хосты + дерево групп + статус версии агента по каждому хосту */
export function useFleet() {
  const hosts = useHosts();
  const groups = useGroups();
  const versions = useAgentVersions();
  const tree = useMemo(() => buildGroupTree(groups.data ?? [], hosts.data ?? []), [groups.data, hosts.data]);
  const versionOf = useMemo(() => {
    const map = new Map<string, VersionStatus>();
    versions.data?.hosts.forEach((h) => map.set(h.host_id, h.version_status));
    return (host: Host): VersionStatus => (host.has_agent ? map.get(host.id) ?? "unknown" : "no_agent");
  }, [versions.data]);
  const hostById = useMemo(() => new Map((hosts.data ?? []).map((h) => [h.id, h])), [hosts.data]);
  return {
    hosts: hosts.data ?? [],
    groups: groups.data ?? [],
    tree,
    hostById,
    versionOf,
    agentVersions: versions.data,
    isLoading: hosts.isLoading || groups.isLoading,
    error: hosts.error || groups.error,
  };
}

export const useTasks = (params: Record<string, unknown>, refetchInterval: number | false = 5000) =>
  useQuery({ queryKey: keys.tasks(params), queryFn: () => get<TaskRun[]>("/tasks", params), refetchInterval });

export const useTask = (id: string | null) =>
  useQuery({
    queryKey: keys.task(id ?? ""),
    queryFn: () => get<TaskRunDetail>(`/tasks/${id}`),
    enabled: !!id,
    refetchInterval: (query) => (["queued", "running"].includes(query.state.data?.status ?? "") ? 2000 : false),
  });

export const useRepos = () => {
  const canEdit = useCanEdit();
  return useQuery({ queryKey: keys.repos, queryFn: () => get<Repo[]>("/playbooks/repos"), enabled: canEdit });
};
export const usePlaybookFiles = (repoId: string | null) =>
  useQuery({ queryKey: keys.files(repoId ?? ""), queryFn: () => get<PlaybookFile[]>(`/playbooks/repos/${repoId}/files`), enabled: !!repoId });
export const useSchedules = () => {
  const canEdit = useCanEdit();
  return useQuery({ queryKey: keys.schedules, queryFn: () => get<Schedule[]>("/playbooks/schedules"), enabled: canEdit });
};

export const useSoftwarePackages = (params: { name?: string; exclude_system: boolean }) =>
  useQuery({
    queryKey: keys.packages(params),
    queryFn: () => get<SoftwarePackage[]>("/software/packages", { ...params, name: params.name || undefined }),
    placeholderData: (previous) => previous,
  });
export const useHostSoftware = (hostId: string | null) =>
  useQuery({ queryKey: keys.hostSoftware(hostId ?? ""), queryFn: () => get<SoftwareItem[]>("/software", { host_id: hostId }), enabled: !!hostId });
export const usePackageHosts = (name: string | null) =>
  useQuery({ queryKey: keys.packageHosts(name ?? ""), queryFn: () => get<SoftwareItem[]>("/software/package-hosts", { name }), enabled: !!name });

export const useInstallers = () =>
  useQuery({
    queryKey: keys.installers,
    queryFn: () => get<InstallerFile[]>("/installers").then((files) => files.filter((f) => !f.name.toLowerCase().endsWith(".version"))),
  });

export const useAlertSummary = (days = 7) =>
  useQuery({ queryKey: ["alerts-summary", days], queryFn: () => get<AlertSummary>("/agent/alerts/summary", { days }) });

export const useAlerts = (hostId?: string) =>
  useQuery({ queryKey: keys.alerts(hostId), queryFn: () => get<AgentAlert[]>("/agent/alerts", { host_id: hostId, limit: 50 }) });
