import { ReactNode, useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg";
}

const SIZES = { sm: "max-w-md", md: "max-w-2xl", lg: "max-w-4xl" };
const FOCUSABLE = "button, input, select, textarea, a[href], summary, [contenteditable], [tabindex]";

export default function Modal({ open, onClose, title, children, footer, size = "md" }: ModalProps) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const close = useRef(onClose);
  useEffect(() => { close.current = onClose; }, [onClose]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!open || !dialog) return;
    const opener = document.activeElement;
    const isTopmost = () => {
      const modals = document.querySelectorAll("[data-modal]");
      return dialog.closest("[data-modal]") === modals[modals.length - 1];
    };
    if (!dialog.contains(document.activeElement)) titleRef.current?.focus();

    const onFocus = (event: FocusEvent) => {
      if (isTopmost() && event.target instanceof Node && !dialog.contains(event.target)) titleRef.current?.focus();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || !isTopmost()) return;
      if (event.key === "Escape") {
        event.preventDefault();
        close.current();
      }
      if (event.key !== "Tab") return;
      const visible = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((item) =>
        item.tabIndex >= 0 && !item.matches(":disabled") && !item.closest("[inert]") &&
        item.getClientRects().length > 0 && getComputedStyle(item).visibility === "visible",
      );
      const checkedRadios = new Set(visible.flatMap((item) =>
        item instanceof HTMLInputElement && item.type === "radio" && item.checked && item.name ? [item.name] : [],
      ));
      const items = visible.filter((item) => !(item instanceof HTMLInputElement && item.type === "radio" && !item.checked && checkedRadios.has(item.name)));
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (!first || !items.includes(active as HTMLElement) || (event.shiftKey ? active === first : active === last)) {
        event.preventDefault();
        (event.shiftKey ? last : first)?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("focusin", onFocus);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("focusin", onFocus);
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus({ preventScroll: true });
    };
  }, [open]);

  if (!open) return null;
  return createPortal(
    <div data-modal className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-4 sm:pt-[6vh]">
      <div className="fixed inset-0 animate-fade-in bg-slate-950/50" onClick={onClose} />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={`relative flex max-h-[88vh] w-full ${SIZES[size]} animate-scale-in flex-col rounded-xl border border-border bg-background shadow-panel-lg`}
      >
        <header className="flex items-center gap-3 border-b border-border px-5 py-3.5">
          <h2 id={titleId} ref={titleRef} tabIndex={-1} className="flex-1 text-base font-semibold text-foreground">{title}</h2>
          <button type="button" className="btn-ghost btn-icon -mr-2" onClick={onClose} aria-label="Закрыть">
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-border px-5 py-3">{footer}</footer>}
      </div>
    </div>,
    document.body,
  );
}
