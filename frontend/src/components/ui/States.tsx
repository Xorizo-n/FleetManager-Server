import { ReactNode } from "react";
import { Loader2 } from "lucide-react";
import Button from "./Button";

export function Loading({ label = "Загрузка…", className = "" }: { label?: string; className?: string }) {
  return (
    <div className={`flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground ${className}`}>
      <Loader2 className="h-4 w-4 animate-spin" />
      {label}
    </div>
  );
}

export function Empty({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`py-10 text-center text-sm text-subtle ${className}`}>{children}</div>;
}

export function ErrorText({ children }: { children: ReactNode }) {
  return children ? (
    <p role="alert" className="text-sm text-rose-600 dark:text-rose-400">
      {children}
    </p>
  ) : null;
}

export function LoadError({ children, onRetry, retrying }: { children: ReactNode; onRetry: () => void; retrying?: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-2 py-3">
      <ErrorText>{children}</ErrorText>
      <Button type="button" variant="secondary" size="sm" onClick={onRetry} loading={retrying}>Повторить</Button>
    </div>
  );
}
