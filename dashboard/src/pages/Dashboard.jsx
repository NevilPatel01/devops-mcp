import { useCallback, useEffect, useState } from "react";
import ApprovalCard from "../components/ApprovalCard.jsx";
import ExecutionLog from "../components/ExecutionLog.jsx";
import ServerGrid from "../components/ServerGrid.jsx";
import IncidentFeed from "../components/IncidentFeed.jsx";
import { connect, getStatus, on } from "../ws.js";

export default function Dashboard() {
  const [wsStatus, setWsStatus] = useState("disconnected");
  const [servers, setServers] = useState([]);
  const [phase, setPhase] = useState(0);
  const [pendingAction, setPendingAction] = useState(null);
  const [executingActionId, setExecutingActionId] = useState(null);

  const clearPending = useCallback(() => setPendingAction(null), []);

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
    refresh();
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
    };
  }, [clearPending]);

  return (
    <motionPage>
      <header className="border-b border-slate-800 bg-slate-900/80 px-6 py-4">
        <PageHeader phase={phase} wsStatus={wsStatus} />
      </header>
      <main className="mx-auto max-w-6xl space-y-6 px-6 py-8">
        <ApprovalCard action={pendingAction} onClear={clearPending} />
        <ExecutionLog activeActionId={executingActionId} />
        <ServerGrid servers={servers} />
        <IncidentFeed />
      </main>
    </motionPage>
  );
}

function motionPage({ children }) {
  return <div className="min-h-screen">{children}</div>;
}

function PageHeader({ phase, wsStatus }) {
  return (
    <motionHeaderInner>
      <div>
        <h1 className="text-xl font-semibold tracking-tight">DevOps AI Agent</h1>
        <p className="text-sm text-slate-400">
          Phase {phase} · WebSocket {wsStatus}
        </p>
      </div>
      <button
        type="button"
        disabled
        className="rounded-lg bg-slate-700 px-3 py-1.5 text-sm text-slate-400"
        title="Phase 4"
      >
        Generate handoff
      </button>
    </motionHeaderInner>
  );
}

function motionHeaderInner({ children }) {
  return (
    <div className="mx-auto flex max-w-6xl items-center justify-between">{children}</div>
  );
}
