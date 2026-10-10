import { Plus, X } from "lucide-react";

export interface VarPair {
  key: string;
  value: string;
}

export function varsToObject(pairs: VarPair[]): Record<string, string> {
  return Object.fromEntries(pairs.filter((p) => p.key.trim()).map((p) => [p.key.trim(), p.value]));
}

export function objectToVars(vars: Record<string, unknown> | null | undefined): VarPair[] {
  const pairs = Object.entries(vars ?? {}).map(([key, value]) => ({ key, value: String(value) }));
  return pairs.length ? pairs : [];
}

export default function ExtraVarsEditor({ value, onChange }: { value: VarPair[]; onChange: (pairs: VarPair[]) => void }) {
  const update = (index: number, field: keyof VarPair, text: string) =>
    onChange(value.map((pair, i) => (i === index ? { ...pair, [field]: text } : pair)));

  return (
    <div className="space-y-2">
      {value.map((pair, i) => (
        <div key={i} className="flex gap-2">
          <input placeholder="переменная" value={pair.key} onChange={(e) => update(i, "key", e.target.value)} className="input-base w-1/3 py-1.5 font-mono" />
          <input placeholder="значение" value={pair.value} onChange={(e) => update(i, "value", e.target.value)} className="input-base flex-1 py-1.5" />
          <button type="button" className="btn-ghost btn-icon" onClick={() => onChange(value.filter((_, j) => j !== i))} aria-label="Удалить переменную">
            <X className="h-4 w-4" />
          </button>
        </div>
      ))}
      <button type="button" onClick={() => onChange([...value, { key: "", value: "" }])} className="btn-ghost btn-sm">
        <Plus className="h-3.5 w-3.5" />
        Переменная
      </button>
    </div>
  );
}
