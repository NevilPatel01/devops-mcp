import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchJson } from "../api.js";
import { connect, on } from "../ws.js";
import { avgLatency, sortSitesByUrgency } from "../lib/fleet.js";
import AddServerWizard from "../components/fleet/AddServerWizard.jsx";
import AddSiteWizard from "../components/fleet/AddSiteWizard.jsx";
import SiteTable from "../components/fleet/SiteTable.jsx";
import ApprovalCard from "../components/ApprovalCard.jsx";
import { IconSearch, IconServer } from "../components/ui/icons.jsx";

const FILTERS = [
  { id: "all", label: "All sites" },
  { id: "down", label: "Down" },
  { id: "up", label: "Up" },
];

export default function SitesPage({
  onStatsChange,
  onNavigate,
  showServer,
  setShowServer,
  showSite,
  setShowSite,
}) {
  const [sites, setSites] = useState([]);
  const [servers, setServers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [showServerLocal, setShowServerLocal] = useState(false);
  const [showSiteLocal, setShowSiteLocal] = useState(false);
  const serverOpen = showServer ?? showServerLocal;
  const siteOpen = showSite ?? showSiteLocal;
  const openServer = setShowServer ?? setShowServerLocal;
  const openSite = setShowSite ?? setShowSiteLocal;
  const closeServer = () => (setShowServer ? setShowServer(false) : setShowServerLocal(false));
  const closeSite = () => (setShowSite ? setShowSite(false) : setShowSiteLocal(false));
  const [checkingAll, setCheckingAll] = useState(false);
  const [pendingAction, setPendingAction] = useState(null);

  const load = useCallback(async () => {
    const [sitesRes, serversRes] = await Promise.all([
      fetchJson("/api/fleet/sites"),
      fetchJson("/api/fleet/servers"),
    ]);
    if (sitesRes.ok && sitesRes.data?.sites) setSites(sitesRes.data.sites);
    if (serversRes.ok && serversRes.data?.servers) setServers(serversRes.data.servers);
    setLoading(false);
    onStatsChange?.();
  }, [onStatsChange]);

  useEffect(() => {
    connect();
    load();
    const offSite = on("site_update", (msg) => {
      if (!msg.site_id || !msg.data) return;
      setSites((prev) => prev.map((s) => (s.id === msg.site_id ? { ...s, ...msg.data } : s)));
      onStatsChange?.();
    });
    const offPending = on("action_pending", (msg) => {
      if (msg.action) setPendingAction(msg.action);
    });
    const offReminder = on("action_pending_reminder", (msg) => {
      if (msg.action) setPendingAction(msg.action);
    });
    const offDone = on("action_executed", () => setPendingAction(null));
    const offReject = on("action_rejected", () => setPendingAction(null));
    return () => {
      offSite();
      offPending();
      offReminder();
      offDone();
      offReject();
    };
  }, [load, onStatsChange]);

  const filtered = useMemo(() => {
    let list = sites;
    if (filter === "down") list = list.filter((s) => (s.uptime_status || s.status) === "down");
    if (filter === "up") list = list.filter((s) => (s.uptime_status || s.status) === "up");
    if (query.trim()) {
      const q = query.toLowerCase();
      list = list.filter(
        (s) =>
          s.name?.toLowerCase().includes(q) ||
          s.client_name?.toLowerCase().includes(q) ||
          s.url?.toLowerCase().includes(q) ||
          s.server_label?.toLowerCase().includes(q)
      );
    }
    return sortSitesByUrgency(list);
  }, [sites, filter, query]);

  const downSites = sites.filter((s) => (s.uptime_status || s.status) === "down");
  const latencyAvg = avgLatency(sites);

  const checkAll = async () => {
    const withUrl = sites.filter((s) => s.url);
    if (!withUrl.length) return;
    setCheckingAll(true);
    await Promise.all(
      withUrl.map((s) => fetchJson(`/api/fleet/sites/${s.id}/probe`, { method: "POST" }))
    );
    setCheckingAll(false);
    load();
  };

  if (loading) {
    return <p className="py-16 text-center text-sm text-zinc-500">Loading fleet…</p>;
  }

  if (sites.length === 0 && servers.length === 0) {
    return (
      <div className="py-16 text-center">
        <div className="panel mx-auto max-w-md p-10">
          <IconServer className="mx-auto h-10 w-10 text-zinc-600" />
          <h2 className="mt-4 text-lg font-semibold text-white">Start monitoring your sites</h2>
          <p className="mt-2 text-sm text-zinc-500">
            Connect a VPS via SSH, add client sites with URLs, and see live uptime for your whole fleet in one place.
          </p>
          <button type="button" className="btn-primary mt-6 w-full" onClick={() => openServer(true)}>
            Connect first server
          </button>
        </div>
        <AddServerWizard open={serverOpen} onClose={closeServer} onSuccess={load} />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {pendingAction && (
        <ApprovalCard action={pendingAction} onClear={() => setPendingAction(null)} />
      )}

      {downSites.length > 0 && (
        <div className="alert-banner alert-banner-down">
          <div>
            <p className="font-medium text-red-200">
              {downSites.length} site{downSites.length === 1 ? "" : "s"} currently down
            </p>
            <p className="mt-0.5 text-xs text-red-300/70">
              {downSites.map((s) => s.name).join(" · ")}
            </p>
          </div>
          <button type="button" className="btn-secondary text-xs" onClick={() => setFilter("down")}>
            Show down only
          </button>
        </div>
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <SummaryCard label="Total sites" value={sites.length} />
        <SummaryCard
          label="Healthy"
          value={sites.filter((s) => (s.uptime_status || s.status) === "up").length}
          tone="up"
        />
        <SummaryCard label="Down" value={downSites.length} tone={downSites.length ? "down" : undefined} />
        <SummaryCard
          label="Avg latency"
          value={latencyAvg != null ? `${latencyAvg} ms` : "—"}
          sub="across checked sites"
        />
      </div>

      {/* Toolbar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="segment">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              onClick={() => setFilter(f.id)}
              className={filter === f.id ? "segment-btn-active" : "segment-btn"}
            >
              {f.label}
              {f.id === "down" && downSites.length > 0 && (
                <span className="ml-1 text-red-400">{downSites.length}</span>
              )}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[160px] flex-1 sm:flex-none sm:w-48">
            <IconSearch className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-600" />
            <input
              type="search"
              placeholder="Filter sites…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="input-field py-2 pl-9 text-xs"
            />
          </div>
          <button
            type="button"
            className="btn-secondary text-xs"
            onClick={checkAll}
            disabled={checkingAll || !sites.some((s) => s.url)}
          >
            {checkingAll ? "Checking…" : "Check all now"}
          </button>
          <button type="button" className="btn-secondary text-xs sm:hidden" onClick={() => openServer(true)}>
            Server
          </button>
          <button
            type="button"
            className="btn-primary text-xs sm:hidden"
            onClick={() => openSite(true)}
            disabled={servers.length === 0}
          >
            Add site
          </button>
        </div>
      </div>

      {/* Site table */}
      {filtered.length === 0 ? (
        <p className="py-12 text-center text-sm text-zinc-500">No sites match this filter.</p>
      ) : (
        <SiteTable sites={filtered} onRefresh={load} onStatsChange={onStatsChange} />
      )}

      {servers.length > 0 && sites.length === 0 && (
        <p className="text-center text-sm text-zinc-500">
          Server connected —{" "}
          <button type="button" className="text-white underline" onClick={() => openSite(true)}>
            add your first site
          </button>
        </p>
      )}

      {/* Servers */}
      {servers.length > 0 && (
        <section className="panel p-4">
          <h3 className="text-xs font-medium uppercase tracking-wider text-zinc-500">
            Connected servers ({servers.length})
          </h3>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {servers.map((srv) => (
              <div
                key={srv.id}
                className="flex items-center justify-between rounded-lg border border-surface-border bg-black/20 px-3 py-2.5"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-zinc-200">{srv.label}</p>
                  <p className="truncate font-mono text-xs text-zinc-500">{srv.host}</p>
                </div>
                <span className="shrink-0 text-xs text-zinc-600">{srv.ssh_user || "root"}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      <AddServerWizard open={serverOpen} onClose={closeServer} onSuccess={load} />
      <AddSiteWizard open={siteOpen} onClose={closeSite} onSuccess={load} servers={servers} />
    </div>
  );
}

function SummaryCard({ label, value, tone, sub }) {
  const color =
    tone === "up" ? "text-emerald-400" : tone === "down" ? "text-red-400" : "text-white";
  return (
    <div className="panel px-4 py-3">
      <p className={`text-2xl font-semibold tabular-nums tracking-tight ${color}`}>{value}</p>
      <p className="mt-0.5 text-xs text-zinc-500">{label}</p>
      {sub && <p className="text-[10px] text-zinc-600">{sub}</p>}
    </div>
  );
}
