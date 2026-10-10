import { FormEvent, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { FolderPlus, Trash2 } from "lucide-react";
import { apiClient } from "../../api/client";
import { keys, useCredentials, useFleet } from "../../api/queries";
import type { TreeNode } from "../../lib/groupTree";
import PageHeader from "../../components/ui/PageHeader";
import Button from "../../components/ui/Button";
import Modal from "../../components/ui/Modal";
import SearchInput from "../../components/ui/SearchInput";
import { Empty, ErrorText, Loading } from "../../components/ui/States";
import { useToast } from "../../components/ui/Toast";
import { apiError, pcCount } from "../../lib/format";

/** Группы хостов: учётка группы (наследуется вниз по дереву), ручные группы. */
export default function Groups() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { tree, isLoading } = useFleet();
  const credentials = useCredentials();
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState(false);
  const credentialOptions = (credentials.data ?? []).filter((c) => !c.is_agent_managed);
  const credentialName = (id: string | null) => (id ? credentials.data?.find((c) => c.id === id)?.name ?? "—" : null);

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    const result: { node: TreeNode; inherited: { from: string; credentialId: string } | null }[] = [];
    const walk = (node: TreeNode, inherited: { from: string; credentialId: string } | null) => {
      if (!node.group) return;
      if (!q || node.path.toLowerCase().includes(q)) result.push({ node, inherited });
      const own = node.group.credential_id ? { from: node.path, credentialId: node.group.credential_id } : inherited;
      node.children.forEach((child) => walk(child, own));
    };
    tree.roots.forEach((root) => walk(root, null));
    return result;
  }, [tree, search]);

  async function setCredential(node: TreeNode, credentialId: string) {
    try {
      await apiClient.patch(`/hosts/groups/${node.id}`, { credential_id: credentialId || null });
      queryClient.invalidateQueries({ queryKey: keys.groups });
      queryClient.invalidateQueries({ queryKey: keys.credentials });
      toast({ tone: "success", message: `${node.path}: учётка ${credentialId ? "назначена" : "снята"}` });
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось изменить группу") });
    }
  }

  async function remove(node: TreeNode) {
    if (!window.confirm(`Удалить группу «${node.path}»? ПК группы (${node.hostIds.length}) останутся без группы, подгруппы поднимутся на уровень выше.`)) return;
    try {
      await apiClient.delete(`/hosts/groups/${node.id}`);
      queryClient.invalidateQueries({ queryKey: keys.groups });
      queryClient.invalidateQueries({ queryKey: keys.hosts });
      toast({ tone: "success", message: `Группа удалена: ${node.path}` });
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось удалить группу") });
    }
  }

  return (
    <div className="animate-fade-in space-y-4">
      <PageHeader
        title="Группы хостов"
        description="Корпуса, этажи и аудитории сервер создаёт сам по имени ПК. Учётка группы действует для всех ПК внутри, если у ПК нет своей."
        actions={
          <Button size="sm" onClick={() => setCreating(true)}>
            <FolderPlus className="h-3.5 w-3.5" />
            Ручная группа
          </Button>
        }
      />
      <SearchInput value={search} onChange={setSearch} placeholder="Поиск группы" className="max-w-sm" />
      {isLoading ? (
        <Loading />
      ) : (
        <div className="table-shell">
          <table className="table-base">
            <thead>
              <tr>
                <th>Группа</th>
                <th>ПК</th>
                <th className="w-[22rem]">Учётные данные SSH</th>
                <th className="w-12" />
              </tr>
            </thead>
            <tbody>
              {rows.map(({ node, inherited }) => (
                <tr key={node.id}>
                  <td>
                    <div className="flex items-center gap-2" style={{ paddingLeft: node.depth * 18 }}>
                      <Link to={`/hosts?group=${node.id}`} className="font-medium text-foreground hover:underline">{node.name}</Link>
                      {!node.group!.is_auto && <span className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">ручная</span>}
                    </div>
                    {node.group!.description && <div className="text-xs text-subtle" style={{ paddingLeft: node.depth * 18 }}>{node.group!.description}</div>}
                  </td>
                  <td className="tabular-nums text-muted-foreground">{pcCount(node.hostIds.length)}</td>
                  <td>
                    <select value={node.group!.credential_id ?? ""} onChange={(e) => setCredential(node, e.target.value)} className="input-base py-1.5" aria-label={`Учётка группы ${node.path}`}>
                      <option value="">{inherited ? `Наследуется: ${credentialName(inherited.credentialId)}` : "Не задана"}</option>
                      {credentialOptions.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                    </select>
                    {!node.group!.credential_id && inherited && <div className="mt-0.5 text-xs text-subtle">от {inherited.from}</div>}
                  </td>
                  <td className="text-right">
                    {!node.group!.is_auto && (
                      <button className="action-danger" onClick={() => remove(node)} aria-label={`Удалить ${node.path}`}>
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && <Empty>Групп нет</Empty>}
        </div>
      )}
      {creating && <CreateGroupDialog onClose={() => setCreating(false)} />}
    </div>
  );
}

function CreateGroupDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { tree } = useFleet();
  const [form, setForm] = useState({ name: "", parent_id: "", description: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiClient.post("/hosts/groups", { name: form.name.trim(), parent_id: form.parent_id || null, description: form.description.trim() || null });
      queryClient.invalidateQueries({ queryKey: keys.groups });
      toast({ tone: "success", message: `Группа создана: ${form.name}` });
      onClose();
    } catch (err) {
      setError(apiError(err, "Не удалось создать группу"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open onClose={onClose} title="Ручная группа" size="sm">
      <form onSubmit={submit} className="space-y-3">
        <p className="text-sm text-muted-foreground">ПК в группу добавляются на странице «Хосты»: выберите их и нажмите «Ещё → Назначить группу».</p>
        <div>
          <label className="field-label" htmlFor="group-name">Название</label>
          <input id="group-name" required autoFocus value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="input-base" placeholder="Преподаватели" />
        </div>
        <div>
          <label className="field-label" htmlFor="group-parent">Внутри группы</label>
          <select id="group-parent" value={form.parent_id} onChange={(e) => setForm({ ...form, parent_id: e.target.value })} className="input-base">
            <option value="">Верхний уровень</option>
            {tree.options.map((g) => <option key={g.id} value={g.id}>{g.label}</option>)}
          </select>
        </div>
        <div>
          <label className="field-label" htmlFor="group-desc">Описание</label>
          <input id="group-desc" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="input-base" />
        </div>
        <div className="flex items-center justify-end gap-2">
          <ErrorText>{error}</ErrorText>
          <Button type="button" variant="secondary" onClick={onClose}>Отмена</Button>
          <Button type="submit" loading={busy}>Создать</Button>
        </div>
      </form>
    </Modal>
  );
}
