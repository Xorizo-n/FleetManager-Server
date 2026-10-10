import { useEffect, useState } from "react";

/** Значение, которое обновляется только после паузы во вводе (поиск без запроса на каждую клавишу). */
export function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}
