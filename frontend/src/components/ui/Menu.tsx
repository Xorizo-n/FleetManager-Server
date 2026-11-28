import { KeyboardEvent, MouseEvent, ReactNode, useEffect, useId, useLayoutEffect, useRef, useState } from "react";

export interface MenuItem {
  id?: string;
  label: string;
  icon?: ReactNode;
  onClick: () => void;
  danger?: boolean;
  disabled?: boolean;
  hint?: string;
  keepOpen?: boolean;
}

interface MenuProps {
  trigger: (props: { open: boolean; toggle: (event: MouseEvent) => void; id: string }) => ReactNode;
  items: (MenuItem | "divider")[];
  align?: "left" | "right";
  direction?: "down" | "up";
  header?: ReactNode;
}

export default function Menu({ trigger, items, align = "right", direction = "down", header }: MenuProps) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const ref = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const initialFocus = useRef<"first" | "last" | null>(null);
  const nativeFocusGroup = "focusGroup" in HTMLElement.prototype;
  const enabledItems = () => [...(listRef.current?.querySelectorAll<HTMLButtonElement>("button:enabled") ?? [])];
  const focusTrigger = () => document.getElementById(id)?.focus();

  useLayoutEffect(() => {
    if (!open || !initialFocus.current) return;
    const options = enabledItems();
    options.at(initialFocus.current === "first" ? 0 : -1)?.focus();
    initialFocus.current = null;
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape" && open) {
      event.preventDefault();
      event.stopPropagation();
      focusTrigger();
      setOpen(false);
      return;
    }
    const { key } = event;
    if (key !== "ArrowDown" && key !== "ArrowUp" && key !== "Home" && key !== "End") return;
    if (!open && key !== "ArrowDown" && key !== "ArrowUp") return;
    if (nativeFocusGroup && listRef.current?.contains(event.target as Node)) return;
    event.preventDefault();
    if (!open) {
      initialFocus.current = key === "ArrowUp" ? "last" : "first";
      setOpen(true);
      return;
    }
    const options = enabledItems();
    const index = options.indexOf(document.activeElement as HTMLButtonElement);
    if (key === "Home" || (index === -1 && key === "ArrowDown")) options[0]?.focus();
    else if (key === "End" || index === -1) options.at(-1)?.focus();
    else options.at((index + (key === "ArrowDown" ? 1 : -1) + options.length) % options.length)?.focus();
  }

  return (
    <div
      ref={ref}
      className="relative"
      onKeyDown={onKeyDown}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget) ||
          (event.relatedTarget?.id === id && event.target.id !== id)) setOpen(false);
      }}
    >
      {trigger({ id, open, toggle: (event) => {
        initialFocus.current = event.detail === 0 ? "first" : null;
        setOpen(!open);
      } })}
      {open && (
        <div
          className={`absolute z-50 min-w-[220px] animate-scale-in rounded-xl border border-border bg-surface py-1 shadow-panel-lg ${
            align === "right" ? "right-0" : "left-0"
          } ${direction === "down" ? "top-full mt-1" : "bottom-full mb-1"}`}
        >
          {header}
          <div ref={listRef} role={nativeFocusGroup ? undefined : "menu"} {...{ focusgroup: "menu nomemory" }} aria-labelledby={id}>
            {items.map((item, i) =>
              item === "divider" ? (
                <hr key={`d${i}`} className="my-1 border-t border-border" />
              ) : (
                <button
                  key={item.id ?? item.label}
                  type="button"
                  role={nativeFocusGroup ? undefined : "menuitem"}
                  tabIndex={nativeFocusGroup ? undefined : -1}
                  disabled={item.disabled}
                  title={item.hint}
                  onClick={() => {
                    if (!item.keepOpen) {
                      focusTrigger();
                      setOpen(false);
                    }
                    item.onClick();
                  }}
                  className={`flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm transition-colors focus-visible:bg-muted disabled:cursor-not-allowed disabled:opacity-40 ${
                    item.danger ? "text-rose-600 hover:bg-rose-500/10 dark:text-rose-400" : "text-foreground hover:bg-muted"
                  }`}
                >
                  {item.icon && <span aria-hidden="true" className="flex h-4 w-4 items-center justify-center text-muted-foreground">{item.icon}</span>}
                  {item.label}
                </button>
              ),
            )}
          </div>
        </div>
      )}
    </div>
  );
}
