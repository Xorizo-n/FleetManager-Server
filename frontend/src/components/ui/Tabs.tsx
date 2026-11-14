interface TabsProps<T extends string> {
  tabs: { id: T; label: string; count?: number }[];
  value: T;
  onChange: (id: T) => void;
  idPrefix?: string;
  wrap?: boolean;
}

export default function Tabs<T extends string>({ tabs, value, onChange, idPrefix, wrap }: TabsProps<T>) {
  return (
    <div role="tablist" className={`flex gap-1 border-b border-border ${wrap ? "flex-wrap" : "overflow-x-auto overflow-y-hidden"}`}>
      {tabs.map((t, index) => (
        <button
          key={t.id}
          role="tab"
          id={idPrefix && `${idPrefix}-tab-${t.id}`}
          aria-controls={idPrefix && `${idPrefix}-panel-${t.id}`}
          aria-selected={value === t.id}
          tabIndex={idPrefix && value !== t.id ? -1 : 0}
          onClick={() => onChange(t.id)}
          onKeyDown={(event) => {
            if (!idPrefix) return;
            const nextIndex = event.key === "ArrowRight" ? (index + 1) % tabs.length
              : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length
              : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null;
            if (nextIndex === null) return;
            event.preventDefault();
            const next = tabs[nextIndex].id;
            onChange(next);
            document.getElementById(`${idPrefix}-tab-${next}`)?.focus();
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
