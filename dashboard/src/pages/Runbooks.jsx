import { useCallback, useEffect, useState } from "react";

export default function Runbooks() {
  const [runbooks, setRunbooks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const q = filter ? `?status=${encodeURIComponent(filter)}` : "";
      const res = await fetch(`/api/runbooks${q}`);
      const data = await res.json();
      if (data.success) setRunbooks(data.runbooks || []);
      else setError(data.error || "Failed to load runbooks");
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    load();
  }, [load]);

  const approve = async (runbookId, autoExecutable) => {
    setError(null);
    try {
      const res = await fetch(`/api/runbooks/${runbookId}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          auto_executable: autoExecutable,
          approved_by: "dashboard",
        }),
      });
      const data = await res.json();
      if (!data.success) setError(data.error || "Approve failed");
      else await load();
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <header className="mb-6">
        <h1 className="text-xl font-semibold text-slate-100">Runbooks</h1>
        <p className="mt-1 text-sm text-slate-500">
          Draft runbooks from resolved incidents; approve to auto-match future anomalies.
        </p>
      </header>

      <div className="mb-4 flex gap-2">
        {["", "draft", "approved", "archived"].map((s) => (
          <button
            key={s || "all"}
            type="button"
            onClick={() => setFilter(s)}
            className={`rounded-lg px-3 py-1 text-sm ${
              filter === s
                ? "bg-slate-700 text-slate-100"
                : "bg-slate-800/50 text-slate-400 hover:text-slate-200"
            }`}
          >
            {s || "all"}
          </button>
        ))}
      </div>

      {error && (
        <p className="mb-4 rounded-lg border border-red-900/50 bg-red-950/40 px-3 py-2 text-sm text-red-300">
          {error}
        </p>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : runbooks.length === 0 ? (
        <p className="text-sm text-slate-500">
          No runbooks yet. Resolve an incident and use Generate runbook on the incident
          detail panel, or wait for auto-draft after successful remediation.
        </p>
      ) : (
        <ul className="space-y-3">
          {runbooks.map((rb) => (
            <li
              key={rb.runbook_id || rb.id}
              className="rounded-xl border border-slate-800 bg-slate-900/60 p-4"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <span className="font-medium text-slate-200">
                    {rb.service_name || "any"} · {rb.incident_type}
                  </span>
                  <span
                    className={`ml-2 rounded px-2 py-0.5 text-xs ${
                      rb.status === "approved"
                        ? "bg-emerald-900/50 text-emerald-300"
                        : rb.status === "draft"
                          ? "bg-amber-900/50 text-amber-300"
                          : "bg-slate-800 text-slate-400"
                    }`}
                  >
                    {rb.status}
                  </span>
                  {rb.auto_executable ? (
                    <span className="ml-2 text-xs text-cyan-400">auto-exec</span>
                  ) : null}
                </div>
                {rb.status === "draft" && (
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => approve(rb.runbook_id, false)}
                      className="rounded-lg bg-slate-700 px-3 py-1 text-sm text-slate-200 hover:bg-slate-600"
                    >
                      Approve
                    </button>
                    <button
                      type="button"
                      onClick={() => approve(rb.runbook_id, true)}
                      className="rounded-lg bg-cyan-900/60 px-3 py-1 text-sm text-cyan-200 hover:bg-cyan-800/60"
                    >
                      Approve + auto-exec
                    </button>
                  </div>
                )}
              </div>
              <pre className="mt-2 max-h-32 overflow-auto rounded bg-slate-950/80 p-2 text-xs text-slate-400">
                {JSON.stringify(rb.steps, null, 2)}
              </pre>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
