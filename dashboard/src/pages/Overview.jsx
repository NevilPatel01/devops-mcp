import { useCallback, useEffect, useState } from "react";
import ApprovalCard from "../components/ApprovalCard.jsx";
import ExecutionLog from "../components/ExecutionLog.jsx";
import { fetchJson } from "../api.js";
import { connect, on } from "../ws.js";

export default function OverviewPage({ onNavigate }) {
  const [pendingAction, setPendingAction] = useState(null);
  const [executingActionId, setExecutingActionId] = useState(null);
  const [sites, setSites] = useState([]);
  const [openIncidents, setOpenIncidents] = useState(0);

  const load = useCallback(async () => {
    const [sitesRes, incRes] = await Promise.all([
      fetchJson("/api/fleet/sites"),
      fetchJson("/api/incidents"),
    ]);
    if (sitesRes.ok) setSites(sitesRes.data?.sites || []);
    if (incRes.ok) {
      setOpenIncidents(
        (incRes.data?.incidents || []).filter((i) => i.status === "open").length
      );
    }
  }, []);

  useEffect(() => {
    connect();
    load();
    const offPending = on("action_pending", (msg) => {
      if (msg.action) setPendingAction(msg.action);
    });
    const offReminder = on("action_pending_reminder", (msg) => {
      if (msg.action) setPendingAction(msg.action);
    });
    const offExecuted = on("action_executed", () => setPendingAction(null));
    const offRejected = on("action_rejected", () => setPendingAction(null));
    const offExecuting = on("action_executing", (msg) => {
      if (msg.action_id) setExecutingActionId(msg.action_id);
    });
    const offSite = on("site_update", load);
    return () => {
      offPending();
      offReminder();
      offExecuted();
      offRejected();
      offExecuting();
      offSite();
    };
  }, [load]);

  const down = sites.filter((s) => (s.uptime_status || s.status) === "down");
  const hasOps = pendingAction || executingActionId || down.length > 0 || openIncidents > 0;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-white">Alerts</h1>
        <p className="mt-0.5 text-sm text-zinc-500">Pending approvals and issues requiring action.</p>
      </div>

      <ApprovalCard action={pendingAction} onClear={() => setPendingAction(null)} />
      {executingActionId && <ExecutionLog activeActionId={executingActionId} />}

      {!hasOps && sites.length > 0 && (
        <div className="panel px-6 py-14 text-center">
          <p className="font-medium text-emerald-400">All clear</p>
          <p className="mt-1 text-sm text-zinc-500">No pending actions or down sites.</p>
          <button type="button" className="btn-ghost mt-4 text-xs" onClick={() => onNavigate?.("sites")}>
            View fleet →
          </button>
        </div>
      )}

      {down.length > 0 && (
        <section className="panel overflow-hidden">
          <div className="border-b border-surface-border px-4 py-3">
            <h2 className="text-sm font-medium text-red-300">
              {down.length} site{down.length === 1 ? "" : "s"} down
            </h2>
          </div>
          <ul className="divide-y divide-surface-border">
            {down.map((s) => (
              <li key={s.id} className="flex items-center justify-between gap-3 px-4 py-3 text-sm">
                <div className="min-w-0">
                  <p className="truncate text-zinc-200">{s.name}</p>
                  <p className="truncate text-xs text-zinc-500">{s.url || s.server_label}</p>
                </div>
                <span className="badge-down shrink-0">down</span>
              </li>
            ))}
          </ul>
          <div className="border-t border-surface-border px-4 py-2">
            <button type="button" className="btn-ghost text-xs" onClick={() => onNavigate?.("sites")}>
              Open fleet →
            </button>
          </div>
        </section>
      )}

      {openIncidents > 0 && !pendingAction && (
        <button
          type="button"
          onClick={() => onNavigate?.("incidents")}
          className="panel w-full px-4 py-4 text-left transition hover:border-amber-500/30"
        >
          <p className="text-sm font-medium text-amber-200">
            {openIncidents} open incident{openIncidents === 1 ? "" : "s"}
          </p>
          <p className="mt-0.5 text-xs text-zinc-500">Review timeline →</p>
        </button>
      )}

      {sites.length === 0 && !pendingAction && (
        <div className="panel px-6 py-10 text-center">
          <p className="text-sm text-zinc-500">No sites monitored yet.</p>
          <button type="button" className="btn-primary mt-4 text-xs" onClick={() => onNavigate?.("sites")}>
            Set up fleet
          </button>
        </div>
      )}
    </div>
  );
}
