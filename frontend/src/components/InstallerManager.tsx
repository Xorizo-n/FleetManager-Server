import { useEffect, useRef, useState } from "react";
import { Download, HardDrive, Search, Trash2, Upload } from "lucide-react";
import { apiClient, getAccessToken } from "../api/client";
import { useAuth } from "../context/AuthContext";
import Button from "./ui/Button";

interface InstallerFile {
  name: string;
  size: number;
  mtime: string;
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} ГБ`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} МБ`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} КБ`;
  return `${bytes} Б`;
}

export default function InstallerManager() {
  const { user } = useAuth();
  const canManage = user?.role === "admin" || user?.role === "operator";

  const [files, setFiles] = useState<InstallerFile[]>([]);
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [uploadStatus, setUploadStatus] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function loadFiles() {
    try {
      const { data } = await apiClient.get<InstallerFile[]>("/installers");
      setFiles(data);
      setError(null);
    } catch (e: any) {
      setError(e.response?.data?.detail || "Не удалось загрузить список файлов");
    }
  }

  useEffect(() => {
    loadFiles();
  }, []);

  async function handleUpload(selected: FileList | null) {
    if (!selected || selected.length === 0) return;
    setUploading(true);
    setError(null);
    try {
      for (const file of Array.from(selected)) {
        const form = new FormData();
        form.append("file", file);
        setUploadStatus(`Загрузка ${file.name}… 0%`);
        await apiClient.post("/installers", form, {
          headers: { "Content-Type": "multipart/form-data" },
          onUploadProgress: (e) => {
            const pct = e.total ? Math.round((e.loaded / e.total) * 100) : 0;
            setUploadStatus(`Загрузка ${file.name}… ${pct}%`);
          },
        });
      }
      setUploadStatus(`Загружено файлов: ${selected.length}`);
      await loadFiles();
    } catch (e: any) {
      setError(e.response?.data?.detail || "Ошибка загрузки файла");
      setUploadStatus(null);
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function handleDelete(name: string) {
    if (!confirm(`Удалить файл ${name} из хранилища установочников?`)) return;
    try {
      await apiClient.delete(`/installers/${encodeURIComponent(name)}`);
      await loadFiles();
    } catch (e: any) {
      setError(e.response?.data?.detail || "Ошибка удаления файла");
    }
  }

  async function handleDownload(name: string) {
    const token = getAccessToken();
    const res = await fetch(`${apiClient.defaults.baseURL}/installers/${encodeURIComponent(name)}/download`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) {
      setError("Не удалось скачать файл");
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  }

  const visible = files.filter((f) => f.name.toLowerCase().includes(search.toLowerCase()));
  const totalSize = files.reduce((acc, f) => acc + f.size, 0);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-subtle" />
          <input
            aria-label="Поиск по имени файла"
            placeholder="Поиск по имени файла"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="input-base w-auto py-2 pl-8 text-sm"
          />
        </div>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <HardDrive className="h-4 w-4" />
            {files.length} файл(ов) · {formatSize(totalSize)}
          </span>
          {canManage && (
            <>
              <input
                ref={inputRef}
                type="file"
                accept=".exe,.msi"
                multiple
                className="hidden"
                onChange={(e) => handleUpload(e.target.files)}
              />
              <Button onClick={() => inputRef.current?.click()} loading={uploading}>
                <Upload className="h-4 w-4" />
                Загрузить
              </Button>
            </>
          )}
        </div>
      </div>

      {uploadStatus && <p className="text-sm text-muted-foreground">{uploadStatus}</p>}
      {error && <p className="text-sm text-rose-600 dark:text-rose-400">{error}</p>}

      <div className="table-shell">
        <table className="table-base">
          <thead>
            <tr>
              <th>Файл</th>
              <th>Размер</th>
              <th>Изменён</th>
              <th className="w-24"></th>
            </tr>
          </thead>
          <tbody>
            {visible.map((f) => (
              <tr key={f.name}>
                <td className="font-mono text-foreground/80">{f.name}</td>
                <td className="whitespace-nowrap tabular-nums">{formatSize(f.size)}</td>
                <td className="whitespace-nowrap text-muted-foreground">
                  {new Date(f.mtime).toLocaleString()}
                </td>
                <td>
                  <div className="flex justify-end gap-1">
                    <button
                      onClick={() => handleDownload(f.name)}
                      aria-label={`Скачать ${f.name}`}
                      className="inline-flex cursor-pointer items-center rounded-md px-2 py-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
                    >
                      <Download className="h-4 w-4" aria-hidden="true" />
                    </button>
                    {canManage && (
                      <button
                        onClick={() => handleDelete(f.name)}
                        aria-label={`Удалить ${f.name}`}
                        className="action-danger"
                      >
                        <Trash2 className="h-4 w-4" aria-hidden="true" />
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {visible.length === 0 && (
              <tr>
                <td colSpan={4} className="py-8 text-center text-subtle">
                  {files.length === 0 ? "В хранилище нет файлов" : "Ничего не найдено"}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
