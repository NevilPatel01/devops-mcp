import { useCallback, useEffect, useState } from "react";
import { fetchJson } from "../../api.js";
import { timeAgo } from "../../lib/fleet.js";

export default function SiteTable({ sites, onRefresh, onStatsChange }) {
  const [expandedId, setExpandedId] = useState(null);
  const [logs, setLogs] = useState({});
  const [busy, setBusy] = useState({});
  const [, tick] = useState(0);

  // Re-render relative times every 15s
  useEffect(() => {
    const id = setInterval(() => tick((t) => t + 1), 15_000);
    return () => clearInterval(id);
  }, []);

  const setSiteBusy = (siteId, key) => setBusy((b) => ({ ...b, [siteId]: key }));
  const clearBusy = (siteId) => setBusy((b) => ({ ...b, [siteId]: null }));

  const probe = async (site) => {
    setSiteBusy(site.id, "probe");
    await fetchJson(`/api/fleet/sites/${site.id}/probe`, { method: "POST" });
    clearBusy(site.id);
    onRefresh?.();
    onStatsChange?.();
  };

  const restart = async (site) => {
    if (site.environment === "production" && !window.confirm(`Restart production container "${site.service_name}"?`)) {
      return;
    }
    setSiteBusy(site.id, "restart");
    await fetchJson(`/api/fleet/sites/${site.id}/restart`, { method: "POST" });
    clearBusy(site.id);
    if (expandedId === site.id) loadLogs(site);
  };

  const loadLogs = useCallback(async (site) => {
    if (!site.service_name) return;
    setSiteBusy(site.id, "logs");
    const res = await fetchJson(`/api/fleet/sites/${site.id}/logs?lines=80`);
    clearBusy(site.id);
    if (res.ok && res.data?.logs) {
      setLogs((l) => ({ ...l, [site.id]: res.data.logs }));
    }
  }, []);

  const toggleExpand = async (site) => {
    if (expandedId === site.id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(site.id);
    if (site.service_name && !logs[site.id]) await loadLogs(site);
  };

  const remove = async (site) => {
    if (!window.confirm(`Remove "${site.name}" from monitoring?`)) return;
    setSiteBusy(site.id, "delete");
    await fetchJson(`/api/fleet/sites/${site.id}`, { method: "DELETE" });
    clearBusy(site.id);
    onRefresh?.();
    onStatsChange?.();
  };

  return (
    <div className="table-wrap">
      <table className="fleet-table">
        <thead>
          <tr>
            <th>Status</th>
            <th>Site</th>
            <th className="hide-sm">URL</th>
            <th>HTTP</th>
            <th>Latency</th>
            <th className="hide-md">Last check</th>
            <th className="hide-lg">Server</th>
            <th className="hide-lg">Container</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {sites.map((site) => {
            const status = site.uptime_status || site.status || "unknown";
            const isExpanded = expandedId === site.id;
            const siteBusy = busy[site.id];

            return (
              <SiteRows
                key={site.id}
                site={site}
                status={status}
                isExpanded={isExpanded}
                siteBusy={siteBusy}
                logs={logs[site.id]}
                onProbe={() => probe(site)}
                onRestart={() => restart(site)}
                onToggle={() => toggleExpand(site)}
                onRemove={() => remove(site)}
                onRefreshLogs={() => loadLogs(site)}
              />
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SiteRows({
  site,
  status,
  isExpanded,
  siteBusy,
  logs,
  onProbe,
  onRestart,
  onToggle,
  onRemove,
  onRefreshLogs,
}) {
  const statusUi = STATUS[status] || STATUS.unknown;

  return (
    <>
      <tr className={`fleet-row ${status === "down" ? "fleet-row-down" : ""}`}>
        <td>
          <span className={`inline-flex items-center gap-2 ${statusUi.text}`}>
            <span className={`h-2 w-2 rounded-full ${statusUi.dot}`} />
            <span className="text-xs font-medium capitalize">{status}</span>
          </span>
        </td>
        <td>
          <div className="min-w-0">
            <p className="truncate font-medium text-zinc-100">{site.name}</p>
            {site.client_name && (
              <p className="truncate text-xs text-zinc-500">{site.client_name}</p>
            )}
          </div>
        </td>
        <td className="hide-sm">
          {site.url ? (
            <a
              href={site.url.startsWith("http") ? site.url : `https://${site.url}`}
              target="_blank"
              rel="noreferrer"
              className="truncate text-xs text-zinc-400 hover:text-white"
              onClick={(e) => e.stopPropagation()}
            >
              {site.url.replace(/^https?:\/\//, "")}
            </a>
          ) : (
            <span className="text-xs text-zinc-600">—</span>
          )}
        </td>
        <td className="tabular-nums text-sm text-zinc-300">
          {site.uptime_status_code ?? "—"}
        </td>
        <td className="tabular-nums text-sm text-zinc-300">
          {site.uptime_latency_ms != null ? `${Math.round(site.uptime_latency_ms)} ms` : "—"}
        </td>
        <td className="hide-md text-xs text-zinc-500">{timeAgo(site.uptime_checked_at)}</td>
        <td className="hide-lg text-xs text-zinc-400">{site.server_label || site.server_id}</td>
        <td className="hide-lg font-mono text-xs text-zinc-500">{site.service_name || "—"}</td>
        <td>
          <div className="flex flex-wrap gap-1">
            {site.url && (
              <ActionChip onClick={onProbe} disabled={!!siteBusy} loading={siteBusy === "probe"}>
                Check
              </ActionChip>
            )}
            {site.service_name && (
              <ActionChip onClick={onRestart} disabled={!!siteBusy} loading={siteBusy === "restart"} warn>
                Restart
              </ActionChip>
            )}
            <ActionChip onClick={onToggle} disabled={!!siteBusy && siteBusy !== "logs"} active={isExpanded}>
              {site.service_name ? "Logs" : "Details"}
            </ActionChip>
          </div>
        </td>
      </tr>
      {isExpanded && (
        <tr className="fleet-row-expanded">
          <td colSpan={9}>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2 text-xs text-zinc-500">
                <p>
                  <span className="text-zinc-600">Server:</span> {site.server_label} ({site.server_host})
                </p>
                <p>
                  <span className="text-zinc-600">Environment:</span> {site.environment || "production"}
                </p>
                {site.cpu_percent != null && (
                  <p>
                    <span className="text-zinc-600">Host CPU / RAM:</span> {Math.round(site.cpu_percent)}% /{" "}
                    {site.memory_percent != null ? `${Math.round(site.memory_percent)}%` : "—"}
                  </p>
                )}
                <p>
                  <span className="text-zinc-600">Last check:</span> {timeAgo(site.uptime_checked_at)}
                </p>
                <button type="button" onClick={onRemove} className="btn-danger-ghost mt-2 text-xs">
                  Remove site
                </button>
              </div>
              {site.service_name ? (
                <div>
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-xs font-medium text-zinc-500">Logs · {site.service_name}</p>
                    <button type="button" onClick={onRefreshLogs} className="btn-ghost px-2 py-1 text-xs">
                      {siteBusy === "logs" ? "…" : "Refresh"}
                    </button>
                  </div>
                  <pre className="log-panel">{logs || (siteBusy === "logs" ? "Loading…" : "No output")}</pre>
                </div>
              ) : (
                <p className="text-xs text-zinc-600">
                  Link a container when adding this site to enable logs and restart.
                </p>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

const STATUS = {
  up: { dot: "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.5)]", text: "text-emerald-400" },
  down: { dot: "bg-red-400 shadow-[0_0_8px_rgba(248,113,113,0.5)]", text: "text-red-400" },
  degraded: { dot: "bg-amber-400", text: "text-amber-400" },
  unknown: { dot: "bg-zinc-500", text: "text-zinc-500" },
};

function ActionChip({ children, onClick, disabled, loading, warn, active }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`rounded-md px-2 py-1 text-[11px] font-medium transition disabled:opacity-40 ${
        active
          ? "bg-white/15 text-white"
          : warn
            ? "bg-amber-500/10 text-amber-200 hover:bg-amber-500/20"
            : "bg-white/5 text-zinc-300 hover:bg-white/10 hover:text-white"
      }`}
    >
      {loading ? "…" : children}
    </button>
  );
}
