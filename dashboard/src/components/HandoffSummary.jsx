import { useEffect, useRef, useState } from "react";
import { fetchJson } from "../api.js";
import { getStatus, on, send } from "../ws.js";

const HANDOFF_TIMEOUT_MS = 90_000;

export default function HandoffSummary({ open, onClose, markdown, loading }) {
  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
      role="presentation"
    >
      <div
        role="dialog"
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-2xl rounded-xl border border-slate-700 bg-slate-900 shadow-xl"
      >
        <div className="flex items-center justify-between border-b border-slate-700 px-4 py-3">
          <h2 className="text-lg font-semibold text-slate-100">Oncall handoff</h2>
          <div className="flex items-center gap-2">
            {markdown && !loading && (
              <button
                type="button"
                onClick={() => navigator.clipboard?.writeText(markdown)}
                className="text-xs text-sky-400 hover:text-sky-300"
              >
                Copy
              </button>
            )}
            <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-200">
              Close
            </button>
          </div>
        </div>
        <HandoffBody loading={loading} markdown={markdown} />
      </div>
    </div>
  );
}

function HandoffBody({ loading, markdown }) {
  return (
    <div className="max-h-[70vh] overflow-y-auto p-4">
      {loading && <p className="text-sm text-slate-500">Generating handoff…</p>}
      {!loading && markdown && (
        <pre className="whitespace-pre-wrap text-sm text-slate-300">{markdown}</pre>
      )}
    </div>
  );
}

export function useHandoff() {
  const [open, setOpen] = useState(false);
  const [markdown, setMarkdown] = useState("");
  const [loading, setLoading] = useState(false);
  const timeoutRef = useRef(null);

  const clearHandoffTimeout = () => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  };

  const finishHandoff = (text) => {
    clearHandoffTimeout();
    if (text !== undefined) setMarkdown(text);
    setLoading(false);
  };

  useEffect(() => {
    const offReady = on("handoff_ready", (msg) => {
      if (msg.success === false) {
        finishHandoff(msg.error || "Handoff failed");
        return;
      }
      finishHandoff(msg.handoff_markdown || "");
    });
    return () => {
      offReady();
      clearHandoffTimeout();
    };
  }, []);

  const request = async () => {
    setOpen(true);
    setLoading(true);
    setMarkdown("");
    clearHandoffTimeout();

    try {
      if (getStatus() === "open") {
        send({ type: "request_handoff" });
        timeoutRef.current = setTimeout(() => {
          setMarkdown((prev) =>
            prev ||
              "Handoff timed out — check server logs or retry when WebSocket is connected."
          );
          timeoutRef.current = null;
        }, HANDOFF_TIMEOUT_MS);
        // WS path skips the HTTP fetch below; clear spinner until handoff_ready or timeout.
        setLoading(false);
        return;
      }

      const result = await fetchJson("/api/handoff");
      if (!result.ok) {
        setMarkdown(result.error || "Handoff request failed");
        return;
      }
      const data = result.data;
      if (data?.success) {
        setMarkdown(data.handoff_markdown || "");
      } else {
        setMarkdown(data?.error || "Handoff failed");
      }
    } catch (e) {
      setMarkdown(String(e));
    } finally {
      setLoading(false);
    }
  };

  return { open, setOpen, markdown, loading, request };
}
