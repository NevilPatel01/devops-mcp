import { useCallback, useEffect, useState } from "react";
import { on } from "../ws.js";

const severityColors = {
  high: "text-red-400",
  medium: "text-amber-400",
  low: "text-emerald-400",
};

const statusFilters = ["all", "open", "resolved", "false_positive"];

export default function IncidentFeed({ onSelect, showFilters = false }) {
  const [incidents, setIncidents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [statusFilter, setStatusFilter] = useState("all");

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/incidents");
      if (!res.ok) {
        const text = await res.text();
        setError(
          res.status === 404
            ? "API not found — restart python server.py (old process may still be on port 8080)"
            : `HTTP ${res.status}: ${text.slice(0, 120)}`
        );
        return;
      }
      const data = await res.json();
      if (data.success) setIncidents(data.incidents || []);
      else setError(data.error || "Failed to load");
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 60000);
    const offCreated = on("incident_created", () => load());
    const offResolved = on("incident_resolved", () => load());
    return () => {
      clearInterval(id);
      offCreated();
      offResolved();
    };
  }, [load]);

  const filtered =
    statusFilter === "all"
      ? incidents
      : incidents.filter((i) => i.status === statusFilter);

  return (
    <section className="panel p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-zinc-200">Timeline</h2>
        <button type="button" onClick={load} className="btn-ghost px-2 py-1 text-xs">
          Refresh
        </button>
      </div>
      {showFilters && (
        <div className="segment mt-3">
          {statusFilters.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setStatusFilter(s)}
              className={`capitalize ${statusFilter === s ? "segment-btn-active" : "segment-btn"}`}
            >
              {s.replace("_", " ")}
            </button>
          ))}
        </div>
      )}
      {loading && <p className="mt-2 text-sm text-slate-500">Loading…</p>}
      {error && <p className="mt-2 text-sm text-red-400">{error}</p>}
      {!loading && filtered.length === 0 && (
        <p className="mt-2 text-sm text-slate-500">No incidents recorded yet.</p>
      )}
      <ul className="mt-3 divide-y divide-surface-border">
        {filtered.map((inc) => (
          <li key={inc.id}>
            <button
              type="button"
              onClick={() => onSelect?.(inc)}
              className="flex w-full flex-wrap items-center gap-2 py-3 text-left transition hover:bg-white/[0.03]"
            >
              <span
                className={`text-xs font-medium uppercase ${
                  severityColors[inc.severity] || "text-slate-400"
                }`}
              >
                {inc.severity || "?"}
              </span>
              <span className="flex-1 text-sm text-slate-200">
                {inc.title}
                {inc.is_sensitive ? (
                  <span
                    className="ml-2 rounded bg-amber-900/40 px-1.5 py-0.5 text-[10px] uppercase text-amber-300"
                    title="Sensitive / compliance-regulated"
                  >
                    sensitive
                  </span>
                ) : null}
              </span>
              <span className="text-xs text-slate-500">{inc.server_id}</span>
              <span className="rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-400">
                {inc.status}
              </span>
              <span className="w-full text-xs text-slate-600">
                {inc.created_at && new Date(inc.created_at).toLocaleString()}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
