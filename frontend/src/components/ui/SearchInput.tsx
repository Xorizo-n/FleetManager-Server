import { InputHTMLAttributes, useId, useRef } from "react";
import { Search, X } from "lucide-react";

interface SearchInputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "onChange" | "value"> {
  value: string;
  onChange: (value: string) => void;
  label: string;
}

export default function SearchInput({ value, onChange, className = "", label, id, ...rest }: SearchInputProps) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const input = useRef<HTMLInputElement>(null);

  return (
    <div className={className}>
      <label htmlFor={inputId} className="field-label">{label}</label>
      <div className="relative">
        <Search aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-subtle" />
        <input
          {...rest}
          id={inputId}
          ref={input}
          type="search"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape" && value && !event.nativeEvent.isComposing) {
              event.preventDefault();
              event.stopPropagation();
              onChange("");
            }
          }}
          className="input-base py-2 pl-8 pr-8 [&::-webkit-search-cancel-button]:hidden"
        />
        {value && (
          <button
            type="button"
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground hover:text-foreground"
            onClick={() => {
              input.current?.focus();
              onChange("");
            }}
            aria-label="Очистить поиск"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    </div>
  );
}
