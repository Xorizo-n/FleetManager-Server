import { RefObject, useEffect, useRef } from "react";

const FOCUSABLE = "button, input, select, textarea, a[href], summary, [contenteditable], [tabindex]";

export function useDialogFocus(open: boolean, onClose: () => void, dialogRef: RefObject<HTMLElement>, titleRef: RefObject<HTMLElement>) {
  const close = useRef(onClose);
  useEffect(() => { close.current = onClose; }, [onClose]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!open || !dialog) return;
    const opener = document.activeElement;
    const isTopmost = () => {
      const modals = document.querySelectorAll("[data-modal]");
      const layers = modals.length ? modals : document.querySelectorAll("[data-drawer]");
      return dialog.closest("[data-modal], [data-drawer]") === layers[layers.length - 1];
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
  }, [open, dialogRef, titleRef]);
}
