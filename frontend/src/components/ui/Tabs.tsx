import { ReactNode, useState } from "react";

interface TabsProps<T extends string> {
  tabs: { id: T; label: ReactNode; count?: number; title?: string }[];
  value: T;
  onChange: (id: T) => void;
  idPrefix: string;
  label: string;
  wrap?: boolean;
  manual?: boolean;
}

export const tabId = (prefix: string, value: string) => `${prefix}-tab-${value}`;

export function TabPanel({ idPrefix, tab, className, children }: {
  idPrefix: string;
  tab: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div role="tabpanel" aria-labelledby={tabId(idPrefix, tab)} tabIndex={0} className={className}>
      {children}
    </div>
  );
}

export default function Tabs<T extends string>({ tabs, value, onChange, idPrefix, label, wrap, manual }: TabsProps<T>) {
  const [focused, setFocused] = useState<T | null>(null);
  const nativeFocusGroup = "focusGroup" in HTMLElement.prototype;
  return (
    <div
      role={nativeFocusGroup ? undefined : "tablist"}
      {...{ focusgroup: "tablist nomemory" }}
      aria-label={label}
      className={`flex gap-1 border-b border-border ${wrap ? "flex-wrap" : "overflow-x-auto overflow-y-hidden"}`}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setFocused(null);
      }}
    >
      {tabs.map((t, index) => (
        <button
          key={t.id}
          type="button"
          role={nativeFocusGroup ? undefined : "tab"}
          id={tabId(idPrefix, t.id)}
          title={t.title}
          aria-selected={value === t.id}
          {...{ focusgroupstart: value === t.id ? "" : undefined }}
          tabIndex={nativeFocusGroup ? undefined : (focused ?? value) === t.id ? 0 : -1}
          onFocus={() => {
            if (!nativeFocusGroup) setFocused(t.id);
            else if (!manual && value !== t.id) onChange(t.id);
          }}
          onClick={() => { if (value !== t.id) onChange(t.id); }}
          onKeyDown={(event) => {
            if (nativeFocusGroup) return;
            const nextIndex = event.key === "ArrowRight" ? (index + 1) % tabs.length
              : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length
              : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null;
            if (nextIndex === null) return;
            event.preventDefault();
            const next = tabs[nextIndex].id;
            document.getElementById(tabId(idPrefix, next))?.focus();
            if (!manual && next !== value) onChange(next);
          }}
          className={`-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
            value === t.id
              ? "border-blue-600 text-foreground"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          {t.label}
          {t.count !== undefined && <span className="ml-1.5 text-xs tabular-nums text-subtle">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}
