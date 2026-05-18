import { useState } from "react";
import { getStatus, send } from "../ws.js";

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

  const request = async () => {
    setOpen(true);
    setLoading(true);
    setMarkdown("");
    if (getStatus() === "open") {
      send({ type: "request_handoff" });
      return;
    }
    try {
      const res = await fetch("/api/handoff");
      if (!res.ok) {
        const text = await res.text();
        setMarkdown(
          res.status === 404
            ? "API not found — restart python server.py (old process may still be on port 8080)"
            : `HTTP ${res.status}: ${text.slice(0, 120)}`
        );
        return;
      }
      const data = await res.json();
      if (data.success) {
        setMarkdown(data.handoff_markdown || "");
      } else {
        setMarkdown(data.error || "Handoff failed");
      }
    } catch (e) {
      setMarkdown(String(e));
    } finally {
      setLoading(false);
    }
  };

  return { open, setOpen, markdown, loading, request };
}
