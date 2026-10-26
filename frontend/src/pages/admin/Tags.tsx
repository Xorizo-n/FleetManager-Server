import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Tag as TagIcon, Trash2 } from "lucide-react";
import { apiClient } from "../../api/client";
import { keys, useTagModels, useTags } from "../../api/queries";
import type { HostTag, HostTagModel } from "../../api/types";
import { useAuth } from "../../context/AuthContext";
import PageHeader from "../../components/ui/PageHeader";
import Button from "../../components/ui/Button";
import Modal from "../../components/ui/Modal";
import { Empty, ErrorText, Loading } from "../../components/ui/States";
import { useToast } from "../../components/ui/Toast";
import { apiError, pcCount } from "../../lib/format";

/** Теги хостов: роль ПК для выбора целей плейбуков. Тег ставится по производителю и модели;
 *  ручной тег на ПК (карточка ПК или «Ещё → Тег…» в реестре) правила не трогают. */
export default function Tags() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin"; // теги и правила меняет администратор
  const queryClient = useQueryClient();
  const toast = useToast();
  const tags = useTags();
  const models = useTagModels();
  const [editing, setEditing] = useState<HostTag | "new" | null>(null);
  const [savingModel, setSavingModel] = useState<string | null>(null);
  const tagList = tags.data ?? [];

  // keys.tags — префикс и для моделей
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: keys.tags }),
      queryClient.invalidateQueries({ queryKey: keys.hosts }),
    ]);

  async function setRule(model: Pick<HostTagModel, "manufacturer" | "model">, tagId: string) {
    const key = `${model.manufacturer}|${model.model}`;
    setSavingModel(key);
    try {
      const { data } = await apiClient.put<{ retagged: number }>("/host-tags/rules", { manufacturer: model.manufacturer, model: model.model, tag_id: tagId || null });
      await refresh();
      toast({ tone: "success", message: data.retagged > 0 ? `Правило сохранено, тег изменился у ${pcCount(data.retagged)}` : "Правило сохранено" });
      return true;
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось сохранить правило") });
      return false;
    } finally {
      setSavingModel(null);
    }
  }

  async function remove(tag: HostTag) {
    const what = [
      tag.host_count > 0 && `${pcCount(tag.host_count)} останутся без него (ручной тег снимется, остальные получат тег по своим правилам)`,
      tag.rule_count > 0 && `правила по модели (${tag.rule_count}) удалятся`,
    ].filter(Boolean);
    if (!window.confirm(`Удалить тег «${tag.name}»?${what.length ? `\n\n${what.join(";\n")}.` : ""}`)) return;
    try {
      await apiClient.delete(`/host-tags/${tag.id}`);
      await refresh();
      toast({ tone: "success", message: `Тег удалён: ${tag.name}` });
    } catch (err) {
      toast({ tone: "error", message: apiError(err, "Не удалось удалить тег") });
    }
  }

  return (
    <div className="animate-fade-in space-y-6">
      <PageHeader
        title="Теги хостов"
        description="Тег — роль ПК: по нему плейбук запускается на все ПК с этим тегом (Автоматизация → Запуск или расписание). Тег ставится по производителю и модели; вручную поставленный тег правила не меняют."
        actions={
          isAdmin && (
            <Button size="sm" onClick={() => setEditing("new")}>
              <Plus className="h-3.5 w-3.5" />
              Новый тег
            </Button>
          )
        }
      />

      {tags.isLoading ? (
        <Loading />
      ) : (
        <div className="table-shell">
          <table className="table-base">
            <thead>
              <tr>
                <th>Тег</th>
                <th>ПК</th>
                <th title="ПК, которым тег поставлен вручную">Из них вручную</th>
                <th>Моделей</th>
                <th>Расписаний</th>
                <th className="w-20" />
              </tr>
            </thead>
            <tbody>
              {tagList.map((t) => (
                <tr key={t.id}>
                  <td>
                    <div className="flex items-center gap-2 font-medium text-foreground">
                      <TagIcon className="h-3.5 w-3.5 text-violet-600 dark:text-violet-400" />
                      {t.name}
                    </div>
                    {t.description && <div className="text-xs text-subtle">{t.description}</div>}
                  </td>
                  <td className="tabular-nums">
                    {t.host_count > 0 ? <Link to={`/hosts?tag=${t.id}`} className="text-foreground hover:underline">{pcCount(t.host_count)}</Link> : <span className="text-subtle">—</span>}
                  </td>
                  <td className="tabular-nums text-muted-foreground">{t.manual_count || "—"}</td>
                  <td className="tabular-nums text-muted-foreground">{t.rule_count || "—"}</td>
                  <td className="tabular-nums text-muted-foreground">{t.schedule_count || "—"}</td>
                  <td className="text-right">
                    {isAdmin && (
                      <div className="inline-flex gap-1">
                        <button className="action-icon" onClick={() => setEditing(t)} aria-label={`Изменить тег ${t.name}`} title="Изменить">
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button
                          className="action-danger disabled:opacity-40"
                          onClick={() => remove(t)}
                          disabled={t.schedule_count > 0}
                          aria-label={`Удалить тег ${t.name}`}
                          title={t.schedule_count > 0 ? "Тег — цель расписаний: сначала уберите его из них" : "Удалить"}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {tagList.length === 0 && <Empty>Тегов нет</Empty>}
        </div>
      )}

      <section className="space-y-3">
        <div>
          <h2 className="text-base font-semibold text-foreground">Тег по модели ПК</h2>
          <p className="text-sm text-muted-foreground">
            Модели из инвентаризации агентов. Изменение сразу применяется ко всем ПК модели, кроме ПК с ручным тегом; новые ПК получают тег при первом heartbeat.
          </p>
        </div>
        {models.isLoading ? (
          <Loading />
        ) : (
          <div className="table-shell">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Производитель</th>
                  <th>Модель</th>
                  <th>ПК</th>
                  <th className="w-[16rem]">Тег</th>
                </tr>
              </thead>
              <tbody>
                {(models.data ?? []).map((m) => {
                  const key = `${m.manufacturer}|${m.model}`;
                  const tagName = tagList.find((t) => t.id === m.tag_id)?.name;
                  return (
                    <tr key={key}>
                      <td className="text-foreground">{m.manufacturer}</td>
                      <td className="font-mono text-xs text-foreground/80">{m.model}</td>
                      <td className="tabular-nums text-muted-foreground">
                        {m.host_count > 0 ? pcCount(m.host_count) : <span className="text-subtle">нет в парке</span>}
                        {m.manual_count > 0 && <div className="text-xs text-subtle">{m.manual_count} с ручным тегом</div>}
                      </td>
                      <td>
                        {isAdmin ? (
                          <select
                            value={m.tag_id ?? ""}
                            disabled={savingModel === key}
                            onChange={(e) => setRule(m, e.target.value)}
                            className="input-base py-1.5"
                            aria-label={`Тег для ${m.manufacturer} ${m.model}`}
                          >
                            <option value="">Без тега</option>
                            {tagList.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                          </select>
                        ) : (
                          <span className={tagName ? "text-foreground" : "text-subtle"}>{tagName ?? "без тега"}</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {models.data?.length === 0 && <Empty>Агенты ещё не прислали модели ПК</Empty>}
          </div>
        )}
        {isAdmin && tagList.length > 0 && <OtherModelRule tags={tagList} onSave={setRule} />}
      </section>

      {editing && <TagEditor tag={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

/** Правило для модели, которой ещё нет в парке (например, перед закупкой) */
function OtherModelRule({ tags, onSave }: { tags: HostTag[]; onSave: (model: { manufacturer: string; model: string }, tagId: string) => Promise<boolean> }) {
  const [form, setForm] = useState({ manufacturer: "", model: "", tag_id: "" });
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    const ok = await onSave({ manufacturer: form.manufacturer.trim(), model: form.model.trim() }, form.tag_id);
    setBusy(false);
    if (ok) setForm({ manufacturer: "", model: "", tag_id: "" });
  }

  return (
    <details className="rounded-lg border border-border px-3 py-2">
      <summary className="cursor-pointer text-sm text-muted-foreground">Правило для модели, которой нет в списке</summary>
      <form onSubmit={submit} className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-[1fr_1fr_12rem_auto] sm:items-end">
        <div>
          <label className="field-label" htmlFor="rule-manufacturer">Производитель</label>
          <input id="rule-manufacturer" required value={form.manufacturer} onChange={(e) => setForm({ ...form, manufacturer: e.target.value })} className="input-base" placeholder="IRBIS" />
        </div>
        <div>
          <label className="field-label" htmlFor="rule-model">Модель</label>
          <input id="rule-model" required value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} className="input-base font-mono" placeholder="GDCS7001HA" />
        </div>
        <div>
          <label className="field-label" htmlFor="rule-tag">Тег</label>
          <select id="rule-tag" required value={form.tag_id} onChange={(e) => setForm({ ...form, tag_id: e.target.value })} className="input-base">
            <option value="">Выберите</option>
            {tags.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </div>
        <Button type="submit" loading={busy}>Добавить</Button>
      </form>
      <p className="mt-2 text-xs text-subtle">Производитель и модель — как в карточке ПК («Оборудование»); регистр и лишние пробелы не важны.</p>
    </details>
  );
}

function TagEditor({ tag, onClose }: { tag: HostTag | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState({ name: tag?.name ?? "", description: tag?.description ?? "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const body = { name: form.name.trim(), description: form.description.trim() || null };
    try {
      if (tag) await apiClient.patch(`/host-tags/${tag.id}`, body);
      else await apiClient.post("/host-tags", body);
      await queryClient.invalidateQueries({ queryKey: keys.tags });
      toast({ tone: "success", message: tag ? "Тег сохранён" : `Тег создан: ${body.name}` });
      onClose();
    } catch (err) {
      setError(apiError(err, "Не удалось сохранить тег"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open onClose={onClose} title={tag ? `Тег «${tag.name}»` : "Новый тег"} size="sm">
      <form onSubmit={submit} className="space-y-3">
        <div>
          <label className="field-label" htmlFor="tag-name">Название</label>
          <input id="tag-name" required autoFocus maxLength={64} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="input-base" placeholder="Преподавательские" />
        </div>
        <div>
          <label className="field-label" htmlFor="tag-desc">Описание</label>
          <input id="tag-desc" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="input-base" />
        </div>
        {!tag && <p className="text-xs text-subtle">Затем выберите тег для моделей ПК ниже или поставьте его ПК вручную в реестре хостов.</p>}
        <div className="flex items-center justify-end gap-2">
          <ErrorText>{error}</ErrorText>
          <Button type="button" variant="secondary" onClick={onClose}>Отмена</Button>
          <Button type="submit" loading={busy}>{tag ? "Сохранить" : "Создать"}</Button>
        </div>
      </form>
    </Modal>
  );
}
