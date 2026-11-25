import { ReactNode, useId } from "react";
import { X } from "lucide-react";
import DialogLayer from "./DialogLayer";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg";
}

const SIZES = { sm: "max-w-md", md: "max-w-2xl", lg: "max-w-4xl" };
export default function Modal({ open, onClose, title, children, footer, size = "md" }: ModalProps) {
  const titleId = useId();
  return (
    <DialogLayer open={open} onClose={onClose} titleId={titleId}>
      <div className={`relative flex max-h-[88vh] w-full ${SIZES[size]} animate-scale-in flex-col rounded-xl border border-border bg-background shadow-panel-lg`}>
        <header className="flex items-center gap-3 border-b border-border px-5 py-3.5">
          <h1 id={titleId} tabIndex={-1} className="flex-1 text-base font-semibold text-foreground">{title}</h1>
          <button type="button" className="btn-ghost btn-icon -mr-2" onClick={onClose} aria-label="Закрыть">
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-border px-5 py-3">{footer}</footer>}
      </div>
    </DialogLayer>
  );
}
