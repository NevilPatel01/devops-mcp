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
    <section className="rounded-xl border border-slate-800 bg-slate-900/50 p-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-200">Incidents</h2>
        <button
          type="button"
          onClick={load}
          className="text-xs text-sky-400 hover:text-sky-300"
        >
          Refresh
        </button>
      </div>
      {showFilters && (
        <div className="mt-3 flex flex-wrap gap-1">
          {statusFilters.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setStatusFilter(s)}
              className={`rounded-full px-2.5 py-0.5 text-xs capitalize ${
                statusFilter === s
                  ? "bg-sky-800 text-sky-100"
                  : "bg-slate-800 text-slate-500 hover:text-slate-300"
              }`}
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
      <ul className="mt-3 divide-y divide-slate-800">
        {filtered.map((inc) => (
          <li key={inc.id}>
            <button
              type="button"
              onClick={() => onSelect?.(inc)}
              className="flex w-full flex-wrap items-center gap-2 py-3 text-left hover:bg-slate-800/40"
            >
              <span
                className={`text-xs font-medium uppercase ${
                  severityColors[inc.severity] || "text-slate-400"
                }`}
              >
                {inc.severity || "?"}
              </span>
              <span className="flex-1 text-sm text-slate-200">{inc.title}</span>
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
