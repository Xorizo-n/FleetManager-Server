import { ReactNode, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  width?: "md" | "lg" | "xl";
}

const WIDTHS = { md: "max-w-xl", lg: "max-w-3xl", xl: "max-w-5xl" };

/** Панель справа поверх страницы: карточка хоста, лог задачи. Закрывается Esc и кликом по фону. */
export default function Drawer({ open, onClose, title, subtitle, actions, children, width = "lg" }: DrawerProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    // Esc закрывает только верхний слой: модальное окно или последнюю открытую панель
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || document.querySelector("[data-modal]")) return;
      const drawers = document.querySelectorAll("[data-drawer]");
      if (drawers[drawers.length - 1] === rootRef.current) onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return createPortal(
    <div ref={rootRef} data-drawer className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 animate-fade-in bg-slate-950/40" onClick={onClose} />
      <aside
        role="dialog"
        aria-modal="true"
        className={`relative flex h-full w-full ${WIDTHS[width]} animate-slide-in-right flex-col border-l border-border bg-background shadow-panel-lg`}
      >
        <header className="flex items-start gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-lg font-semibold text-foreground">{title}</h2>
            {subtitle && <div className="mt-0.5 text-sm text-muted-foreground">{subtitle}</div>}
          </div>
          {actions}
          <button className="btn-ghost btn-icon -mr-2" onClick={onClose} aria-label="Закрыть">
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
      </aside>
    </div>,
    document.body,
  );
}
