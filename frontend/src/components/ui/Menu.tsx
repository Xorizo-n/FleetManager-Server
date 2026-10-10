import { ReactNode, useEffect, useRef, useState } from "react";

export interface MenuItem {
  label: string;
  icon?: ReactNode;
  onClick: () => void;
  danger?: boolean;
  disabled?: boolean;
  hint?: string;
}

interface MenuProps {
  trigger: (props: { open: boolean; toggle: () => void }) => ReactNode;
  items: (MenuItem | "divider")[];
  align?: "left" | "right";
  direction?: "down" | "up";
}

export default function Menu({ trigger, items, align = "right", direction = "down" }: MenuProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      {trigger({ open, toggle: () => setOpen((v) => !v) })}
      {open && (
        <div
          role="menu"
          className={`absolute z-50 min-w-[220px] animate-scale-in rounded-xl border border-border bg-surface py-1 shadow-panel-lg ${
            align === "right" ? "right-0" : "left-0"
          } ${direction === "down" ? "top-full mt-1" : "bottom-full mb-1"}`}
        >
          {items.map((item, i) =>
            item === "divider" ? (
              <div key={`d${i}`} className="my-1 border-t border-border" />
            ) : (
              <button
                key={item.label}
                role="menuitem"
                disabled={item.disabled}
                title={item.hint}
                onClick={() => {
                  setOpen(false);
                  item.onClick();
                }}
                className={`flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
                  item.danger ? "text-rose-600 hover:bg-rose-500/10 dark:text-rose-400" : "text-foreground hover:bg-muted"
                }`}
              >
                {item.icon && <span className="flex h-4 w-4 items-center justify-center text-muted-foreground">{item.icon}</span>}
                {item.label}
              </button>
            ),
          )}
        </div>
      )}
    </div>
  );
}
