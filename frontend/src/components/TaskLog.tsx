import { useEffect, useRef, useState } from "react";
import { apiClient, getAccessToken } from "../api/client";

interface Props {
  taskId: string;
  onDone?: () => void;
}

export default function TaskLog({ taskId, onDone }: Props) {
  const [log, setLog] = useState("");
  const [done, setDone] = useState(false);
  const [finalStatus, setFinalStatus] = useState<string | null>(null);
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

          let eventName = "message";
          let data = "";
          for (const line of rawEvent.split(/\r?\n/)) {
            if (line.startsWith("event:")) eventName = line.slice(6).trim();
            else if (line.startsWith("data:")) data += line.slice(5).trim();
          }

          if (eventName === "log") {
            setLog((prev) => prev + data);
          } else if (eventName === "done") {
            setFinalStatus(data);
            setDone(true);
            onDoneRef.current?.();
            return;
          } else if (eventName === "error") {
            setFinalStatus("error");
            setDone(true);
            onDoneRef.current?.();
            return;
          }
        }
      }
    }

    run().catch(() => {});
    return () => controller.abort();
  }, [taskId]);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [log]);

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
      <pre ref={logRef} className="console-block max-h-[60vh] overflow-y-auto">
        {log || "Ожидание вывода..."}
      </pre>
    </div>
  );
}
