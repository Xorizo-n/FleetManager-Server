import { ImageOff } from "lucide-react";
import { useObservedWallpapers, useWallpapers } from "../api/queries";
import { fileName, thumbnailIndex } from "../lib/wallpapers";
import { useMemo } from "react";

/** Миниатюры каталога и обоев не из каталога по sha256 — одна выборка на страницу */
export function useThumbnails() {
  const catalog = useWallpapers();
  const observed = useObservedWallpapers();
  return useMemo(() => thumbnailIndex(catalog.data, observed.data), [catalog.data, observed.data]);
}

interface Props {
  sha256: string | null | undefined;
  path?: string | null;
  thumbnails: ReturnType<typeof useThumbnails>;
  className?: string;
}

/** Миниатюра обоев: из каталога, присланная агентом или заглушка с именем файла */
export default function WallpaperThumb({ sha256, path, thumbnails, className = "w-40" }: Props) {
  const thumb = sha256 ? thumbnails.get(sha256) : undefined;
  const title = thumb?.name ?? fileName(path) ?? "Обои Windows по умолчанию";
  return (
    <figure className={`min-w-0 ${className}`} title={path ?? undefined}>
      {thumb ? (
        <img src={thumb.src} alt="" className="aspect-video w-full rounded-md border border-border object-cover" />
      ) : (
        <div className="flex aspect-video w-full flex-col items-center justify-center gap-1 rounded-md border border-dashed border-border bg-muted/40 text-xs text-subtle">
          <ImageOff className="h-4 w-4" />
          {sha256 ? "миниатюра придёт с агентом" : path ? "файл не найден" : "не задано"}
        </div>
      )}
      <figcaption className="mt-1 truncate text-xs text-muted-foreground">
        {thumb?.wallpaper ? title : <span className="text-subtle">{title}</span>}
      </figcaption>
    </figure>
  );
}
