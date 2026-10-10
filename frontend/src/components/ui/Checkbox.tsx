import { InputHTMLAttributes, useEffect, useRef } from "react";

interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  indeterminate?: boolean;
}

/** Чекбокс с промежуточным состоянием: выбрана часть ПК группы. */
export default function Checkbox({ indeterminate = false, className = "", ...rest }: CheckboxProps) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate;
  }, [indeterminate]);
  return <input ref={ref} type="checkbox" className={`h-4 w-4 shrink-0 cursor-pointer rounded accent-blue-600 ${className}`} {...rest} />;
}
