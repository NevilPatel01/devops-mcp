import { useCallback, useEffect, useState } from "react";
import ApprovalCard from "../components/ApprovalCard.jsx";
import ExecutionLog from "../components/ExecutionLog.jsx";
import HandoffSummary, { useHandoff } from "../components/HandoffSummary.jsx";
import IncidentDetail from "../components/IncidentDetail.jsx";
import IncidentFeed from "../components/IncidentFeed.jsx";
import ServerGrid from "../components/ServerGrid.jsx";
import ToastStack, { useToasts } from "../components/ToastStack.jsx";
import { connect, getStatus, on } from "../ws.js";

export default function Dashboard() {
  const [wsStatus, setWsStatus] = useState("disconnected");
  const [servers, setServers] = useState([]);
  const [phase, setPhase] = useState(0);
  const [pendingAction, setPendingAction] = useState(null);
  const [executingActionId, setExecutingActionId] = useState(null);
  const [selectedIncident, setSelectedIncident] = useState(null);
  const [openIncidents, setOpenIncidents] = useState(0);
  const handoff = useHandoff();
  const { toasts, push, dismiss } = useToasts();

  const clearPending = useCallback(() => setPendingAction(null), []);

  const refreshOpenCount = useCallback(async () => {
    try {
      const res = await fetch("/api/incidents");
      if (!res.ok) return;
      const data = await res.json();
      if (data.success) {
        setOpenIncidents(
          (data.incidents || []).filter((i) => i.status === "open").length
        );
      }
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    connect();
    const refresh = () => setWsStatus(getStatus());
    const offOpen = on("open", refresh);
    const offClose = on("close", refresh);
    const offConnected = on("connected", (msg) => {
      setPhase(msg.phase ?? 0);
      refresh();
    });
    const offSnapshot = on("snapshot_update", (msg) => {
      setServers((prev) => {
        const next = prev.filter((s) => s.server_id !== msg.server_id);
        return [...next, { server_id: msg.server_id, ...msg.data }];
      });
    });
    const applyPending = (msg) => {
      if (msg.action) setPendingAction(msg.action);
    };
    const offPending = on("action_pending", applyPending);
    const offReminder = on("action_pending_reminder", applyPending);
    const offExecuting = on("action_executing", (msg) => {
      if (msg.action_id) setExecutingActionId(msg.action_id);
    });
    const offExecuted = on("action_executed", (msg) => {
      clearPending();
      if (msg.action_id) setExecutingActionId(msg.action_id);
    });
    const offRejected = on("action_rejected", () => {
      clearPending();
      setExecutingActionId(null);
    });
    const offHandoff = on("handoff_ready", (msg) => {
      handoff.setMarkdown(msg.handoff_markdown || "");
      handoff.setLoading(false);
    });
    const offIncidentCreated = on("incident_created", (msg) => {
      refreshOpenCount();
      push({
        tone: "warning",
        title: "New incident",
        body: msg.incident?.title || "Anomaly detected",
      });
    });
    const offIncidentResolved = on("incident_resolved", (msg) => {
      refreshOpenCount();
      push({
        tone: "success",
        title: "Incident resolved",
        body: msg.postmortem_markdown
          ? "Postmortem drafted — open incident detail to read."
          : undefined,
      });
    });
    const offPendingToast = on("action_pending", (msg) => {
      if (msg.action?.risk_tier === "high") {
        push({
          tone: "warning",
          title: "High-risk action pending",
          body: msg.action.description,
        });
      }
    });
    refresh();
    refreshOpenCount();
    return () => {
      offOpen();
      offClose();
      offConnected();
      offSnapshot();
      offPending();
      offReminder();
      offExecuting();
      offExecuted();
      offRejected();
      offHandoff();
      offIncidentCreated();
      offIncidentResolved();
      offPendingToast();
    };
  }, [clearPending, handoff, push, refreshOpenCount]);

  useEffect(() => {
    const onKey = (e) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
        return;
      }
      if (e.key === "h" || e.key === "H") {
        handoff.request();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [handoff]);

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-800 bg-slate-900/80 px-6 py-4">
        <div className="mx-auto flex max-w-6xl items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">DevOps AI Agent</h1>
            <p className="text-sm text-slate-400">
              Phase {phase} · WebSocket {wsStatus}
            </p>
          </div>
          <div className="flex items-center gap-3">
            {openIncidents > 0 && (
              <span
                className="rounded-full bg-amber-900/50 px-2.5 py-0.5 text-xs font-medium text-amber-200"
                title="Open incidents"
              >
                {openIncidents} open
              </span>
            )}
            <button
              type="button"
              onClick={handoff.request}
              className="rounded-lg bg-sky-700 px-3 py-1.5 text-sm text-white hover:bg-sky-600"
              title="Keyboard shortcut: H"
            >
              Generate handoff
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl space-y-6 px-6 py-8">
        <ApprovalCard action={pendingAction} onClear={clearPending} />
        <ExecutionLog activeActionId={executingActionId} />
        <ServerGrid servers={servers} />
        <IncidentFeed onSelect={setSelectedIncident} />
      </main>
      <HandoffSummary
        open={handoff.open}
        onClose={() => handoff.setOpen(false)}
        markdown={handoff.markdown}
        loading={handoff.loading}
      />
      <IncidentDetail
        incident={selectedIncident}
        onClose={() => setSelectedIncident(null)}
      />
      <ToastStack toasts={toasts} onDismiss={dismiss} />
    </div>
  );
}
