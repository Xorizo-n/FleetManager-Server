import { createContext, ReactNode, useCallback, useContext, useState } from "react";
import { createPortal } from "react-dom";
import { CheckCircle2, Info, X, XCircle } from "lucide-react";

type Tone = "success" | "error" | "info";
interface ToastItem {
  id: number;
  tone: Tone;
  message: string;
  action?: { label: string; onClick: () => void };
}

const ToastContext = createContext<(toast: Omit<ToastItem, "id">) => void>(() => {});

let nextId = 1;

/** Короткие уведомления в углу экрана вместо строк статуса, разбросанных по страницам. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const dismiss = useCallback((id: number) => setItems((list) => list.filter((t) => t.id !== id)), []);
  const push = useCallback(
    (toast: Omit<ToastItem, "id">) => {
      const id = nextId++;
      setItems((list) => [...list.slice(-3), { ...toast, id }]);
      setTimeout(() => dismiss(id), toast.tone === "error" ? 8000 : 4500);
    },
    [dismiss],
  );

  return (
    <ToastContext.Provider value={push}>
      {children}
      {createPortal(
        <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2" aria-live="polite">
          {items.map((t) => {
            const Icon = t.tone === "success" ? CheckCircle2 : t.tone === "error" ? XCircle : Info;
            const color = t.tone === "success" ? "text-emerald-500" : t.tone === "error" ? "text-rose-500" : "text-sky-500";
            return (
              <div key={t.id} className="pointer-events-auto flex animate-slide-up items-start gap-3 rounded-xl border border-border bg-surface px-4 py-3 text-sm shadow-panel-lg">
                <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${color}`} />
                <p className="flex-1 text-foreground">{t.message}</p>
                {t.action && (
                  <button
                    className="shrink-0 font-medium text-blue-600 hover:underline dark:text-blue-400"
                    onClick={() => {
                      t.action!.onClick();
                      dismiss(t.id);
                    }}
                  >
                    {t.action.label}
                  </button>
                )}
                <button className="shrink-0 text-muted-foreground hover:text-foreground" onClick={() => dismiss(t.id)} aria-label="Закрыть">
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            );
          })}
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
