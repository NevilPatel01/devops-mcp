import { useEffect, useRef, useState } from "react";
import { on } from "../ws.js";

export default function ExecutionLog({ activeActionId }) {
  const [lines, setLines] = useState([]);
  const [running, setRunning] = useState(false);
  const [healthWarning, setHealthWarning] = useState(null);
  const bottomRef = useRef(null);

  useEffect(() => {
    if (!activeActionId) {
      setLines([]);
      setRunning(false);
      setHealthWarning(null);
      return undefined;
    }
    setLines([]);
    setHealthWarning(null);

    const offExecuting = on("action_executing", (msg) => {
      if (msg.action_id === activeActionId) setRunning(true);
    });
    const offLine = on("action_log_line", (msg) => {
      if (msg.action_id === activeActionId && msg.line) {
        setLines((prev) => [...prev, msg.line]);
      }
    });
    const offDone = on("action_executed", (msg) => {
      if (msg.action_id !== activeActionId) return;
      setRunning(false);
      if (msg.health_ok === false) {
        setHealthWarning(msg.health_message || "Post-action health check failed");
      }
    });

    return () => {
      offExecuting();
      offLine();
      offDone();
    };
  }, [activeActionId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines]);

  if (!activeActionId && lines.length === 0) return null;

  return (
    <section className="rounded-xl border border-slate-700 bg-slate-950 p-4 font-mono text-sm">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-300">Execution log</h2>
        {running && <span className="animate-pulse text-xs text-sky-400">Running…</span>}
      </div>
      {healthWarning && (
        <p className="mb-2 rounded border border-amber-700 bg-amber-900/30 px-2 py-1 text-xs text-amber-200">
          {healthWarning} — new incident opened. No auto-rollback.
        </p>
      )}
      <pre className="max-h-64 overflow-y-auto whitespace-pre-wrap text-slate-300">
        {lines.length === 0 && running ? (
          <span className="text-slate-500">Waiting for output…</span>
        ) : (
          lines.join("")
        )}
        <span ref={bottomRef} />
      </pre>
    </section>
  );
}
