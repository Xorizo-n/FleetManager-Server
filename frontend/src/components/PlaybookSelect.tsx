import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Check, ChevronDown, Clock } from "lucide-react";
import SearchInput from "./ui/SearchInput";
import type { PlaybookFile } from "../api/types";
import { playbookShortName } from "../lib/format";

const RECENT_KEY = "fm.recentPlaybooks";

/** Плейбук каталога: несколько источников (git-репозитории и локальные из редактора) в одном списке */
export interface CatalogFile extends PlaybookFile {
  /** Уникальный ключ в каталоге: repo_id::path */
  key: string;
  repo_id: string;
  /** Имя источника для группы; у основного git-репозитория пусто — группы по папкам, как раньше */
  source?: string;
  local?: boolean;
}

export const catalogKey = (repoId: string, path: string) => `${repoId}::${path}`;

export function playbookLabel(file: PlaybookFile) {
  return file.display_name || playbookShortName(file.path).replace(/_/g, " ");
}

/** Маски fm_files, которых сейчас нет в шаре: такой плейбук упадёт на каждом ПК */
export function missingShareFiles(file: PlaybookFile) {
  return (file.files ?? []).filter((f) => !f.present).map((f) => f.pattern);
}

/** Что делает плейбук и какие файлы из шары берёт (fm_description, fm_files) — в форме запуска. */
export function PlaybookDetails({ file, heading }: { file: PlaybookFile; heading?: string }) {
  const files = file.files ?? [];
  if (!file.description && files.length === 0) return null;
  const missing = missingShareFiles(file);
  return (
    <div className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs">
      {heading && <p className="mb-0.5 font-medium text-foreground">{heading}</p>}
      {file.description && <p className="text-muted-foreground">{file.description}</p>}
      {files.length > 0 && (
        <ul className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1" aria-label="Файлы из шары">
          {files.map((f) => (
            <li
              key={f.pattern}
              className={`inline-flex items-center gap-1 font-mono ${f.present ? "text-subtle" : "text-amber-600 dark:text-amber-400"}`}
              title={f.present ? `В шаре: ${f.found}` : `Нет в шаре: ${f.pattern}`}
            >
              {f.present ? <Check className="h-3 w-3 text-emerald-500" /> : <AlertTriangle className="h-3 w-3" />}
              {f.found ?? f.pattern}
            </li>
          ))}
        </ul>
      )}
      {missing.length > 0 && (
        <p className="mt-1.5 text-amber-600 dark:text-amber-400">
          В шаре /mnt/soft-share нет {missing.length === 1 ? "файла" : "файлов"} {missing.join(", ")} — плейбук завершится ошибкой на каждом ПК.
        </p>
      )}
    </div>
  );
}

/** Папка внутри репозитория без общего корня: playbooks/install/x.yml -> install */
function folderOf(path: string, commonRoot: string) {
  const parts = path.split("/").slice(0, -1);
  const folder = parts.join("/");
  return (commonRoot && folder.startsWith(commonRoot) ? folder.slice(commonRoot.length).replace(/^\//, "") : folder) || "";
}

function readRecent(): string[] {
  try {
    return JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]");
  } catch {
    return [];
  }
}

export function rememberPlaybook(key: string) {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify([key, ...readRecent().filter((p) => p !== key)].slice(0, 5)));
  } catch {
    // localStorage может быть недоступен — недавние плейбуки просто не запоминаются
  }
}

interface Props {
  files: CatalogFile[];
  /** Ключ выбранного плейбука (catalogKey) */
  value: string;
  onChange: (key: string) => void;
  loading?: boolean;
}

// Недавние до общего каталога хранились путём файла — они относятся к основному git-репозиторию
const isRecent = (f: CatalogFile, saved: string) => f.key === saved || (!f.source && f.path === saved);

/** Каталог плейбуков: поиск, группы по папкам (install, check, diagnose…), недавние сверху. */
export default function PlaybookSelect({ files, value, onChange, loading }: Props) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const commonRoot = useMemo(() => {
    const roots = new Set(files.filter((f) => !f.source).map((f) => (f.path.includes("/") ? f.path.split("/")[0] : "")));
    return roots.size === 1 ? [...roots][0] : "";
  }, [files]);

  const groups = useMemo(() => {
    const q = search.trim().toLowerCase();
    const matched = files.filter(
      (f) => !q || f.path.toLowerCase().includes(q) || playbookLabel(f).toLowerCase().includes(q) || (f.description ?? "").toLowerCase().includes(q),
    );
    const map = new Map<string, CatalogFile[]>();
    if (!q) {
      const recent = readRecent().map((p) => files.find((f) => isRecent(f, p))).filter((f): f is CatalogFile => !!f);
      if (recent.length) map.set("Недавние", recent);
    }
    // Сначала основной репозиторий по папкам, затем остальные источники (локальные — последними)
    const sorted = [...matched].sort((a, b) => Number(!!a.source) - Number(!!b.source) || playbookLabel(a).localeCompare(playbookLabel(b), "ru"));
    for (const f of sorted) {
      const folder = f.source ? [f.source, folderOf(f.path, "")].filter(Boolean).join(" · ") : folderOf(f.path, commonRoot) || "Общие";
      if (!map.has(folder)) map.set(folder, []);
      map.get(folder)!.push(f);
    }
    return [...map.entries()];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [files, search, commonRoot, open]);

  const selected = files.find((f) => f.key === value);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="input-base flex w-full items-center justify-between gap-2 text-left"
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        {selected ? (
          <span className="flex min-w-0 items-baseline gap-2.5">
            <span className="truncate font-medium text-foreground">{playbookLabel(selected)}</span>
            <span className="hidden shrink-0 font-mono text-xs text-subtle sm:inline">{selected.source ? `${selected.source}: ` : ""}{selected.path}</span>
          </span>
        ) : (
          <span className="text-subtle">{loading ? "Загрузка каталога…" : `Выберите плейбук (${files.length})`}</span>
        )}
        <ChevronDown className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-full z-50 mt-1 animate-scale-in overflow-hidden rounded-xl border border-border bg-surface shadow-panel-lg">
          <div className="border-b border-border p-2">
            <SearchInput value={search} onChange={setSearch} placeholder="Поиск по названию, описанию или файлу" autoFocus />
          </div>
          <div className="max-h-80 overflow-y-auto" role="listbox">
            {groups.length === 0 && <p className="px-4 py-6 text-center text-sm text-subtle">Ничего не найдено</p>}
            {groups.map(([folder, items]) => (
              <div key={folder}>
                <div className="sticky top-0 flex items-center gap-1.5 bg-muted/90 px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground backdrop-blur-sm">
                  {folder === "Недавние" && <Clock className="h-3 w-3" />}
                  {folder}
                  <span className="font-normal normal-case tracking-normal text-subtle">{items.length}</span>
                </div>
                {items.map((f) => (
                  <button
                    key={`${folder}-${f.key}`}
                    type="button"
                    role="option"
                    aria-selected={f.key === value}
                    onClick={() => {
                      onChange(f.key);
                      setOpen(false);
                      setSearch("");
                    }}
                    className={`flex w-full flex-col gap-0.5 px-4 py-2 text-left hover:bg-muted ${f.key === value ? "bg-blue-500/10" : ""}`}
                  >
                    <span className="flex w-full items-baseline justify-between gap-3">
                      <span className="flex min-w-0 items-center gap-1.5">
                        <span className="truncate text-sm font-medium text-foreground">{playbookLabel(f)}</span>
                        {missingShareFiles(f).length > 0 && (
                          <AlertTriangle
                            className="h-3.5 w-3.5 shrink-0 text-amber-500"
                            aria-label="Нет файла в шаре"
                          >
                            <title>{`Нет в шаре: ${missingShareFiles(f).join(", ")}`}</title>
                          </AlertTriangle>
                        )}
                      </span>
                      <span className="shrink-0 font-mono text-xs text-subtle">{f.name}</span>
                    </span>
                    {f.description && <span className="w-full truncate text-xs text-muted-foreground">{f.description}</span>}
                  </button>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
