import { apiClient } from "./client";
import type { TaskRun } from "./types";

// Смена учётки SSH всегда идёт через POST /hosts/access-changes: если у какого-то
// ПК меняется учётка, сервер сначала проверяет вход новыми данными и применяет
// изменение только там, где вход прошёл (backend/services/access_change.py).
export type AccessChange =
  | { action: "set_host_credential"; host_ids: string[]; credential_id: string | null }
  | { action: "set_group_credential"; group_id: string; credential_id: string | null }
  | { action: "move_to_group"; host_ids: string[]; group_id?: string | null; group_name?: string | null };

export interface AccessChangeResult {
  task: TaskRun | null; // null: учётка ни у кого не менялась, изменение уже применено
  applied: number;
  to_check: number;
  skipped: number;
}

export async function changeAccess(change: AccessChange) {
  const { data } = await apiClient.post<AccessChangeResult>("/hosts/access-changes", change);
  return data;
}
