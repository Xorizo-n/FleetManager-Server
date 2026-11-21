import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, X } from "lucide-react";
import { apiClient } from "../api/client";
import { useWallpaperAssignments } from "../api/queries";
import type { Host, Wallpaper, WallpaperAssignment } from "../api/types";
import { apiError, hostLabel, plural } from "../lib/format";
import { NO_GROUP, NO_GROUP_LABEL, type GroupTree, type TreeNode } from "../lib/groupTree";
import { KIND_LABELS } from "../lib/wallpapers";
import Button from "./ui/Button";
import Card from "./ui/Card";
import Checkbox from "./ui/Checkbox";
import Modal from "./ui/Modal";
import { ErrorText, Loading } from "./ui/States";
import { useToast } from "./ui/Toast";

type Target = { id: string; label: string; assignments: WallpaperAssignment[] };
type Branch = { id: string; name: string; path: string; own?: Target; hosts: Target[]; children: Branch[]; ids: string[] };

function groupAssignments(assignments: WallpaperAssignment[], tree: GroupTree, hostById: Map<string, Host>): Branch[] {
  const byGroup = new Map<string, Target>();
  const byHost = new Map<string, Target>();
  for (const assignment of assignments) {
    const id = assignment.group_id ?? assignment.host_id;
    if (!id) continue;
    const index = assignment.group_id ? byGroup : byHost;
    let target = index.get(id);
    if (!target) {
      const host = hostById.get(id);
      const label = assignment.group_id ? tree.pathOf(id) : host ? hostLabel(host) : "ПК недоступен";
      target = { id, label, assignments: [] };
      index.set(id, target);
    }
    target.assignments.push(assignment);
  }

  const hostsByGroup = new Map<string, Target[]>();
  for (const target of byHost.values()) {
    const groupId = hostById.get(target.id)?.group_id;
    const key = groupId && tree.byId.has(groupId) ? groupId : NO_GROUP;
    if (!hostsByGroup.has(key)) hostsByGroup.set(key, []);
    hostsByGroup.get(key)!.push(target);
  }

  const idsOf = (targets: Target[]) => targets.flatMap((target) => target.assignments.map((assignment) => assignment.id));
  function build(node: TreeNode): Branch[] {
    const own = byGroup.get(node.id);
    const hosts = (hostsByGroup.get(node.id) ?? []).sort((a, b) => a.label.localeCompare(b.label, "ru", { numeric: true }));
    const children = node.children.flatMap(build);
    const ids = [...idsOf(own ? [own, ...hosts] : hosts), ...children.flatMap((child) => child.ids)];
    return ids.length ? [{ id: node.id, name: node.name, path: node.path, own, hosts, children, ids }] : [];
  }
  const branches = tree.roots.flatMap(build);
  const otherHosts = tree.byId.has(NO_GROUP) ? [] : hostsByGroup.get(NO_GROUP) ?? [];
  if (otherHosts.length) {
    branches.push({
      id: NO_GROUP, name: NO_GROUP_LABEL, path: NO_GROUP_LABEL, hosts: otherHosts, ids: idsOf(otherHosts), children: [],
    });
  }
  for (const own of byGroup.values()) {
    if (!tree.byId.has(own.id)) {
      branches.push({ id: own.id, name: "Группа недоступна", path: own.id, own, hosts: [], children: [], ids: idsOf([own]) });
    }
  }
  return branches;
}

const assignmentCount = (count: number) => plural(count, "назначение", "назначения", "назначений");

export default function WallpaperAssignments({ tree, hostById, catalog, canEdit, fleetLoading }: {
  tree: GroupTree;
  hostById: Map<string, Host>;
  catalog: Map<string, Wallpaper>;
  canEdit: boolean;
  fleetLoading: boolean;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const query = useWallpaperAssignments();
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [confirmIds, setConfirmIds] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const branches = useMemo(() => groupAssignments(query.data ?? [], tree, hostById), [query.data, tree, hostById]);
  const selectedIds = useMemo(() => (query.data ?? []).filter((assignment) => selected.has(assignment.id)).map((assignment) => assignment.id), [query.data, selected]);

  function toggle(ids: string[], checked: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      for (const id of ids) {
        if (checked) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  }

  function askRemove(ids: string[]) {
    setError(null);
    setConfirmIds(ids);
  }

  async function remove() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const { data } = await apiClient.post<{ changed: number }>("/wallpapers/assignments/remove", { assignment_ids: confirmIds });
      await queryClient.invalidateQueries({ queryKey: ["wallpapers", "assignments"] });
      toggle(confirmIds, false);
      setConfirmIds([]);
      toast({ tone: "success", message: data.changed ? `Снято ${assignmentCount(data.changed)}` : "Выбранные назначения уже сняты" });
    } catch (err) {
      setError(apiError(err, "Не удалось снять назначения"));
    } finally {
      setBusy(false);
    }
  }

  function selectionBox(ids: string[], label: string) {
    if (!canEdit) return null;
    const count = ids.filter((id) => selected.has(id)).length;
    return <Checkbox aria-label={label} checked={count === ids.length} indeterminate={count > 0 && count < ids.length}
      onChange={(event) => toggle(ids, event.currentTarget.checked)} />;
  }

  function renderTarget(target: Target, isGroup = false) {
    const ids = target.assignments.map((assignment) => assignment.id);
    return (
      <li key={target.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border py-2">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          {selectionBox(ids, isGroup ? `Выбрать правило группы · ${target.label}` : `Выбрать ПК · ${target.label}`)}
          <span className="break-words text-sm text-foreground">{isGroup ? "Правило группы" : target.label}</span>
        </div>
        <div className="grid w-full gap-2 sm:w-auto sm:grid-cols-2">
          {[...target.assignments].sort((a, b) => a.kind.localeCompare(b.kind)).map((assignment) => {
            const wallpaper = catalog.get(assignment.wallpaper_id);
            const kind = KIND_LABELS[assignment.kind];
            return (
              <div key={assignment.id} className="flex min-w-0 items-center gap-2 sm:w-48">
                {wallpaper && <img src={`data:image/jpeg;base64,${wallpaper.thumbnail_base64}`} alt="" className="h-6 w-10 shrink-0 rounded object-cover" />}
                <div className="min-w-0 flex-1">
                  <p className="text-xs text-muted-foreground">{kind}</p>
                  <p className="truncate text-xs font-medium text-foreground" title={wallpaper?.name}>{wallpaper?.name ?? "Изображение недоступно"}</p>
                </div>
                {canEdit && <button type="button" className="btn-ghost btn-icon shrink-0"
                  aria-label={`Снять ${kind.toLowerCase()} · ${target.label}`} onClick={() => askRemove([assignment.id])}>
                  <X className="h-4 w-4" />
                </button>}
              </div>
            );
          })}
        </div>
      </li>
    );
  }

  function renderBranch(branch: Branch) {
    const open = expanded.has(branch.id);
    const Chevron = open ? ChevronDown : ChevronRight;
    const contentId = `wallpaper-branch-${branch.id}`;
    return (
      <li key={branch.id} className="border-t border-border">
        <div className="flex items-center gap-2">
          {selectionBox(branch.ids, `Выбрать все назначения · ${branch.path}`)}
          <button type="button" aria-expanded={open} aria-controls={contentId}
            className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-1 py-2.5 text-left text-sm hover:bg-muted"
            onClick={() => setExpanded((current) => {
              const next = new Set(current);
              if (next.has(branch.id)) next.delete(branch.id);
              else next.add(branch.id);
              return next;
            })}>
            <Chevron aria-hidden="true" className="h-4 w-4 shrink-0 text-muted-foreground" />
            <span className="min-w-0 flex-1 break-words font-medium text-foreground">{branch.name}</span>
            <span className="shrink-0 px-1 text-xs text-muted-foreground">{assignmentCount(branch.ids.length)}</span>
          </button>
        </div>
        <ul id={contentId} hidden={!open} className="ml-3 border-l border-border pl-2 sm:ml-5 sm:pl-3">
          {open && <>
            {branch.own && renderTarget(branch.own, true)}
            {branch.children.map(renderBranch)}
            {branch.hosts.map((target) => renderTarget(target))}
          </>}
        </ul>
      </li>
    );
  }

  return (
    <Card title="Назначения">
      {query.isLoading || fleetLoading ? <Loading /> : query.isError ? (
        <div className="flex flex-wrap items-center gap-2">
          <ErrorText>Не удалось загрузить назначения.</ErrorText>
          <Button size="sm" variant="secondary" onClick={() => query.refetch()}>Повторить</Button>
        </div>
      ) : branches.length === 0 ? (
        <p className="py-4 text-sm text-muted-foreground">Назначений пока нет. Используйте «Назначить обои», чтобы добавить правило.</p>
      ) : (
        <>
          {canEdit && <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-sm">
            <p aria-live="polite" className="text-muted-foreground">
              {selectedIds.length ? `Выбрано ${assignmentCount(selectedIds.length)}` : "Отметьте группы или ПК для снятия обоев"}
            </p>
            <div className="flex flex-wrap items-center gap-2">
              {!!selectedIds.length && <Button size="sm" variant="secondary" onClick={() => setSelected(new Set())}>Сбросить выбор</Button>}
              <Button size="sm" variant="danger" disabled={!selectedIds.length} onClick={() => askRemove(selectedIds)}>Снять выбранные</Button>
            </div>
          </div>}
          <ul>{branches.map(renderBranch)}</ul>
        </>
      )}
      {canEdit && <Modal open={confirmIds.length > 0} onClose={() => { if (!busy) setConfirmIds([]); }} size="sm"
        title="Снять назначения обоев?"
        footer={<>
          <Button variant="secondary" disabled={busy} onClick={() => setConfirmIds([])}>Отмена</Button>
          <Button variant="danger" loading={busy} onClick={remove}>Снять</Button>
        </>}>
        <p className="text-sm text-foreground">Будет снято {assignmentCount(confirmIds.length)}. Если для ПК есть другое подходящее правило, применятся его обои. Иначе вернутся исходные обои Windows.</p>
        {error && <ErrorText>{error}</ErrorText>}
      </Modal>}
    </Card>
  );
}
