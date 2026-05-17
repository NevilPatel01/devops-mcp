import { useEffect, useState } from "react";
import ServerGrid from "../components/ServerGrid.jsx";
import IncidentFeed from "../components/IncidentFeed.jsx";
import { connect, getStatus, on } from "../ws.js";

export default function Dashboard() {
  const [wsStatus, setWsStatus] = useState("disconnected");
  const [servers, setServers] = useState([]);
  const [phase, setPhase] = useState(0);

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
    refresh();
    return () => {
      offOpen();
      offClose();
      offConnected();
      offSnapshot();
    };
  }, []);

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-800 bg-slate-900/80 px-6 py-4">
        <div className="mx-auto flex max-w-6xl items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">DevOps AI Agent</h1>
            <p className="text-sm text-slate-400">Phase {phase} · WebSocket {wsStatus}</p>
          </div>
          <button
            type="button"
            disabled
            className="rounded-lg bg-slate-700 px-3 py-1.5 text-sm text-slate-400"
            title="Phase 4"
          >
            Generate handoff
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-6xl space-y-6 px-6 py-8">
        <ServerGrid servers={servers} />
        <IncidentFeed />
      </main>
    </div>
  );
}
