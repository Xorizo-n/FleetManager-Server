import { useEffect, useRef, useState } from "react";
import { apiClient, getAccessToken } from "../api/client";

interface Props {
  taskId: string;
  onDone?: (status: string) => void;
}

/** Живой лог задачи через SSE (/tasks/{id}/stream). */
export default function TaskLog({ taskId, onDone }: Props) {
  const [log, setLog] = useState("");
  const [done, setDone] = useState(false);
  const [finalStatus, setFinalStatus] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  const logRef = useRef<HTMLPreElement>(null);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  useEffect(() => {
    const controller = new AbortController();
    setLog("");
    setDone(false);
    setFinalStatus(null);

    async function run() {
      const token = getAccessToken();
      const res = await fetch(`${apiClient.defaults.baseURL}/tasks/${taskId}/stream`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        signal: controller.signal,
      });
      if (!res.body) return;

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done: streamDone } = await reader.read();
        if (streamDone) break;
        buffer += decoder.decode(value, { stream: true });

        let separator: RegExpMatchArray | null;
        while ((separator = buffer.match(/\r?\n\r?\n/)) !== null) {
          const sepIndex = separator.index ?? -1;
          const rawEvent = buffer.slice(0, sepIndex);
          buffer = buffer.slice(sepIndex + separator[0].length);

          // По спецификации SSE строки data: одного события склеиваются через \n,
          // а у значения убирается только один ведущий пробел. Многострочный лог
          // приходит несколькими строками data: и без этого слипался в одну.
          let eventName = "message";
          const dataLines: string[] = [];
          for (const line of rawEvent.split(/\r?\n/)) {
            if (line.startsWith("event:")) eventName = line.slice(6).trim();
            else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
          }
          const data = dataLines.join("\n");

          if (eventName === "log") {
            setLog((prev) => prev + data);
          } else if (eventName === "done" || eventName === "error") {
            const status = eventName === "done" ? data : "error";
            setFinalStatus(status);
            setDone(true);
            onDoneRef.current?.(status);
            return;
          }
        }
      }
    }

    run().catch(() => {});
    return () => controller.abort();
  }, [taskId]);

  useEffect(() => {
    if (follow && logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [log, follow]);

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        {!done ? (
          <>
            <span className="h-1.5 w-1.5 rounded-full bg-sky-400 motion-safe:animate-pulse" />
            Выполняется — лог обновляется в реальном времени
          </>
        ) : (
          <>
            <span className={`h-1.5 w-1.5 rounded-full ${finalStatus === "success" ? "bg-emerald-400" : "bg-rose-400"}`} />
            Завершено: {finalStatus === "success" ? "успешно" : finalStatus === "failed" ? "с ошибкой" : finalStatus}
          </>
        )}
      </div>
      <pre
        ref={logRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          setFollow(el.scrollHeight - el.scrollTop - el.clientHeight < 24);
        }}
        className="console-block max-h-[65vh] overflow-y-auto whitespace-pre-wrap"
      >
        {log || "Ожидание вывода..."}
      </pre>
    </div>
  );
}
