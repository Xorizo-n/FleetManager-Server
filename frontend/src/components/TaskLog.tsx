import { useEffect, useRef, useState } from "react";
import { apiClient, getAccessToken } from "../api/client";

export default function TaskLog({ taskId }: { taskId: string }) {
  const [log, setLog] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const logRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLog("");
    setStatus(null);

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
        const { value, done } = await reader.read();
        if (done) break;
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

          if (eventName === "log") setLog((prev) => prev + data);
          else if (eventName === "done") setStatus(data);
          else if (eventName === "error") setStatus("error");
        }
      }
    }

    run().catch(() => {});
    return () => controller.abort();
  }, [taskId]);

  useEffect(() => {
    logRef.current?.scrollTo(0, logRef.current.scrollHeight);
  }, [log]);

  return (
    <div className="space-y-2">
      {status && (
        <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <span className="h-1.5 w-1.5 rounded-full bg-sky-400 motion-safe:animate-pulse" />
          Статус: {status}
        </p>
      )}
      <pre ref={logRef} className="console-block">
        {log || "Ожидание вывода..."}
      </pre>
    </div>
  );
}
