import { ReactNode, useLayoutEffect, useRef, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";

const layers: HTMLDialogElement[] = [];
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((listener) => listener());
const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
};
const getActiveLayer = () => layers.at(-1) ?? document.body;

export function useDialogPortalTarget() {
  return useSyncExternalStore(subscribe, getActiveLayer);
}

export default function DialogLayer({ open, onClose, titleId, side = false, children }: {
  open: boolean;
  onClose: () => void;
  titleId: string;
  side?: boolean;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const backdropPress = useRef(false);

  useLayoutEffect(() => {
    const dialog = ref.current;
    if (!open || !dialog) return;
    const initial = dialog.querySelector("[data-dialog-autofocus]") ?? document.getElementById(titleId);
    initial?.setAttribute("autofocus", "");
    dialog.showModal();
    layers.push(dialog);
    notify();
    return () => {
      dialog.close();
      const index = layers.indexOf(dialog);
      if (index >= 0) layers.splice(index, 1);
      notify();
    };
  }, [open, titleId]);

  if (!open) return null;
  return createPortal(
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      className={`dialog-layer fixed inset-0 m-0 h-full max-h-none w-full max-w-none overflow-y-auto bg-transparent text-foreground ${
        side ? "justify-end backdrop:bg-slate-950/40" : "items-start justify-center p-4 backdrop:bg-slate-950/50 sm:pt-[6vh]"
      }`}
      onCancel={(event) => {
        event.preventDefault();
        event.stopPropagation();
        onClose();
      }}
      onPointerDown={(event) => {
        backdropPress.current = event.button === 0 && event.target === event.currentTarget;
      }}
      onClick={(event) => {
        if (backdropPress.current && event.target === event.currentTarget) onClose();
        backdropPress.current = false;
      }}
    >
      {children}
    </dialog>,
    document.body,
  );
}
