import { ReactNode } from "react";
import { Loader2 } from "lucide-react";

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
