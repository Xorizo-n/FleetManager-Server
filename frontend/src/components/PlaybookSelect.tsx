import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, Clock } from "lucide-react";
import SearchInput from "./ui/SearchInput";
import type { PlaybookFile } from "../api/types";
import { playbookShortName } from "../lib/format";

const RECENT_KEY = "fm.recentPlaybooks";

export function playbookLabel(file: PlaybookFile) {
  return file.display_name || playbookShortName(file.path).replace(/_/g, " ");
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

export function rememberPlaybook(path: string) {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify([path, ...readRecent().filter((p) => p !== path)].slice(0, 5)));
  } catch {
    // localStorage может быть недоступен — недавние плейбуки просто не запоминаются
  }
}

interface Props {
  files: PlaybookFile[];
  value: string;
  onChange: (path: string) => void;
  loading?: boolean;
}

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
    const roots = new Set(files.map((f) => (f.path.includes("/") ? f.path.split("/")[0] : "")));
    return roots.size === 1 ? [...roots][0] : "";
  }, [files]);

  const groups = useMemo(() => {
    const q = search.trim().toLowerCase();
    const matched = files.filter((f) => !q || f.path.toLowerCase().includes(q) || playbookLabel(f).toLowerCase().includes(q));
    const map = new Map<string, PlaybookFile[]>();
    if (!q) {
      const recent = readRecent().map((p) => files.find((f) => f.path === p)).filter((f): f is PlaybookFile => !!f);
      if (recent.length) map.set("Недавние", recent);
    }
    for (const f of [...matched].sort((a, b) => playbookLabel(a).localeCompare(playbookLabel(b), "ru"))) {
      const folder = folderOf(f.path, commonRoot) || "Общие";
      if (!map.has(folder)) map.set(folder, []);
      map.get(folder)!.push(f);
    }
    return [...map.entries()];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [files, search, commonRoot, open]);

  const selected = files.find((f) => f.path === value);

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
            <span className="hidden shrink-0 font-mono text-xs text-subtle sm:inline">{selected.path}</span>
          </span>
        ) : (
          <span className="text-subtle">{loading ? "Загрузка каталога…" : `Выберите плейбук (${files.length})`}</span>
        )}
        <ChevronDown className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-full z-50 mt-1 animate-scale-in overflow-hidden rounded-xl border border-border bg-surface shadow-panel-lg">
          <div className="border-b border-border p-2">
            <SearchInput value={search} onChange={setSearch} placeholder="Поиск по названию или файлу" autoFocus />
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
                    key={`${folder}-${f.path}`}
                    type="button"
                    role="option"
                    aria-selected={f.path === value}
                    onClick={() => {
                      onChange(f.path);
                      setOpen(false);
                      setSearch("");
                    }}
                    className={`flex w-full items-baseline justify-between gap-3 px-4 py-2 text-left hover:bg-muted ${f.path === value ? "bg-blue-500/10" : ""}`}
                  >
                    <span className="truncate text-sm font-medium text-foreground">{playbookLabel(f)}</span>
                    <span className="shrink-0 font-mono text-xs text-subtle">{f.name}</span>
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
