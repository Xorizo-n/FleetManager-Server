import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Hand, Tag } from "lucide-react";
import { apiClient } from "../api/client";
import { keys, useTagModels, useTags } from "../api/queries";
import type { Host, HostTag } from "../api/types";
import { apiError, pcCount } from "../lib/format";
import { useToast } from "./ui/Toast";

// Теги хостов (backend/services/host_tags.py): у ПК один тег — по правилу «производитель + модель»
// или вручную. Ручной тег правила не трогают, пока его не вернут «по правилу».

export function useTagById() {
  const tags = useTags();
  return useMemo(() => new Map((tags.data ?? []).map((t) => [t.id, t])), [tags.data]);
}

/** ПК, на которые сейчас раскрываются теги */
export function tagHostIds(hosts: Host[], tagIds: Iterable<string>) {
  const set = new Set(tagIds);
  return set.size === 0 ? [] : hosts.filter((h) => h.tag_id && set.has(h.tag_id)).map((h) => h.id);
}

export function TagBadge({ tag, manual, className = "" }: { tag: HostTag | undefined; manual?: boolean; className?: string }) {
  if (!tag) return null;
  return (
    <span
      className={`inline-flex max-w-[10rem] shrink-0 items-center gap-1 rounded bg-violet-500/10 px-1.5 py-px text-[11px] font-medium text-violet-700 dark:text-violet-300 ${className}`}
      title={manual ? `Тег «${tag.name}» поставлен вручную` : `Тег «${tag.name}» — по модели ПК`}
    >
      {manual ? <Hand className="h-3 w-3 shrink-0" /> : <Tag className="h-3 w-3 shrink-0" />}
      <span className="truncate">{tag.name}</span>
    </span>
  );
}

/** Ручной тег ПК: tagId — тег, null — вручную без тега; byRule — снова по модели */
export function useAssignTag() {
  const queryClient = useQueryClient();
  const toast = useToast();
  return async (hostIds: string[], choice: { tagId: string | null } | { byRule: true }) => {
    try {
      await apiClient.post("/host-tags/assign", "byRule" in choice ? { host_ids: hostIds, by_rule: true } : { host_ids: hostIds, tag_id: choice.tagId });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.hosts }),
        queryClient.invalidateQueries({ queryKey: keys.tags }),
      ]);
      return true;
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось изменить тег") });
      return false;
    }
  };
}

const BY_RULE = "__rule";
const NONE = "__none";

/** Тег в карточке ПК: «по модели», ручной тег или вручную без тега — сохраняется сразу */
export function HostTagSelect({ host, disabled }: { host: Host; disabled?: boolean }) {
  const tags = useTags();
  const models = useTagModels();
  const assign = useAssignTag();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const tagById = useTagById();
  const ruleTag = useMemo(() => {
    const key = (s: string | null | undefined) => (s ?? "").split(/\s+/).filter(Boolean).join(" ").toLowerCase();
    const model = models.data?.find((m) => key(m.manufacturer) === key(host.hw_manufacturer) && key(m.model) === key(host.hw_model));
    return model?.tag_id ? tagById.get(model.tag_id) : undefined;
  }, [models.data, host.hw_manufacturer, host.hw_model, tagById]);
  const value = !host.tag_manual ? BY_RULE : host.tag_id ?? NONE;

  async function change(next: string) {
    setBusy(true);
    const ok = await assign([host.id], next === BY_RULE ? { byRule: true } : { tagId: next === NONE ? null : next });
    setBusy(false);
    if (ok) toast({ tone: "success", message: next === BY_RULE ? "Тег снова ставится по модели ПК" : "Тег сохранён" });
  }

  return (
    <div>
      <label className="field-label" htmlFor="host-tag">Тег</label>
      <select id="host-tag" disabled={disabled || busy} value={value} onChange={(e) => change(e.target.value)} className="input-base">
        <option value={BY_RULE}>По модели ПК: {ruleTag ? ruleTag.name : "правила нет — без тега"}</option>
        {(tags.data ?? []).map((t) => <option key={t.id} value={t.id}>{t.name} — вручную</option>)}
        <option value={NONE}>Без тега — вручную</option>
      </select>
      <p className="mt-1 text-xs text-subtle">
        {host.tag_manual ? "Поставлен вручную: правила по модели этот ПК не меняют." : "Ставится по производителю и модели — правила на странице «Теги хостов»."}
      </p>
    </div>
  );
}

/** Выбор тегов как цели запуска: все ПК с тегом на момент запуска */
export function TagTargets({ value, onChange, hosts }: { value: Set<string>; onChange: (next: Set<string>) => void; hosts: Host[] }) {
  const tags = useTags();
  const counts = useMemo(() => {
    const map = new Map<string, { total: number; online: number }>();
    for (const h of hosts) {
      if (!h.tag_id) continue;
      const c = map.get(h.tag_id) ?? { total: 0, online: 0 };
      c.total += 1;
      if (h.status === "online") c.online += 1;
      map.set(h.tag_id, c);
    }
    return map;
  }, [hosts]);
  const list = tags.data ?? [];
  if (list.length === 0) return null;

  function toggle(id: string) {
    const next = new Set(value);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onChange(next);
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="mr-1 inline-flex items-center gap-1 text-xs text-muted-foreground">
        <Tag className="h-3.5 w-3.5" />
        По тегу:
      </span>
      {list.map((t) => {
        const on = value.has(t.id);
        const c = counts.get(t.id) ?? { total: 0, online: 0 };
        return (
          <button
            key={t.id}
            type="button"
            aria-pressed={on}
            onClick={() => toggle(t.id)}
            className={`${on ? "chip-on" : "chip-off"} gap-1.5 ${!on && c.total === 0 ? "opacity-50" : ""}`}
            title={`${t.name}: ${pcCount(c.total)}, online ${c.online}${t.description ? ` — ${t.description}` : ""}`}
          >
            {t.name}
            <span className={`tabular-nums ${on ? "" : "text-subtle"}`}>{c.total}</span>
          </button>
        );
      })}
    </div>
  );
}
