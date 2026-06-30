import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchJson } from "../../api.js";

export default function SiteDetailPanel({ site, onClose, onChange, embedded = false }) {
  const [logs, setLogs] = useState("");
  const [logsLoading, setLogsLoading] = useState(false);
  const [actionBusy, setActionBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [confirmRestart, setConfirmRestart] = useState(false);

  const loadLogs = useCallback(async () => {
    if (!site?.service_name) return;
    setLogsLoading(true);
    setError("");
    const res = await fetchJson(`/api/fleet/sites/${site.id}/logs?lines=120`);
    setLogsLoading(false);
    if (res.ok && res.data?.logs) setLogs(res.data.logs);
    else setError(res.data?.error || res.error || "Could not load logs");
  }, [site]);

  useEffect(() => {
    if (site) {
      setLogs("");
      setMessage("");
      setError("");
      setConfirmRestart(false);
      if (site.service_name) loadLogs();
    }
  }, [site, loadLogs]);

  if (!site) {
    if (embedded) {
      return (
        <div className="flex flex-1 flex-col items-center justify-center px-8 text-center">
          <p className="text-sm text-zinc-500">Select a site to view status, logs, and actions.</p>
        </div>
      );
    }
    return null;
  }

  const status = site.uptime_status || site.status || "unknown";
  const isProd = site.environment === "production";

  const probe = async () => {
    setActionBusy("probe");
    setMessage("");
    setError("");
    const res = await fetchJson(`/api/fleet/sites/${site.id}/probe`, { method: "POST" });
    setActionBusy("");
    if (res.ok && res.data?.success) {
      setMessage("Uptime check complete");
      onChange?.(res.data.site);
    } else {
      setError(res.data?.error || res.error || "Check failed");
    }
  };

  const restart = async () => {
    setActionBusy("restart");
    setMessage("");
    setError("");
    const res = await fetchJson(`/api/fleet/sites/${site.id}/restart`, { method: "POST" });
    setActionBusy("");
    setConfirmRestart(false);
    if (res.ok && res.data?.success) {
      setMessage("Container restarted");
      setTimeout(loadLogs, 1500);
    } else {
      setError(res.data?.error || res.error || "Restart failed");
    }
  };

  const remove = async () => {
    if (!window.confirm(`Remove site "${site.name}"?`)) return;
    setActionBusy("delete");
    const res = await fetchJson(`/api/fleet/sites/${site.id}`, { method: "DELETE" });
    setActionBusy("");
    if (res.ok) {
      onChange?.(null);
      onClose?.();
    } else {
      setError(res.error || "Delete failed");
    }
  };

  const inner = (
    <>
      <header className="flex shrink-0 items-start justify-between gap-3 border-b border-surface-border px-5 py-4">
        <div className="min-w-0">
          {site.client_name && <p className="text-xs text-zinc-500">{site.client_name}</p>}
          <h2 className="truncate text-base font-semibold text-white">{site.name}</h2>
          {site.url && (
            <a
              href={site.url.startsWith("http") ? site.url : `https://${site.url}`}
              target="_blank"
              rel="noreferrer"
              className="mt-0.5 inline-block text-sm text-zinc-400 hover:text-white"
            >
              {site.url.replace(/^https?:\/\//, "")} ↗
            </a>
          )}
        </div>
        {!embedded && (
          <button type="button" onClick={onClose} className="btn-ghost px-2 py-1 text-lg leading-none">
            ×
          </button>
        )}
      </header>

      <div className="flex-1 overflow-y-auto px-5 py-4">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
          <Item label="Status" value={status} highlight={status === "down"} />
          <Item label="HTTP" value={site.uptime_status_code != null ? String(site.uptime_status_code) : "—"} />
          <Item
            label="Latency"
            value={site.uptime_latency_ms != null ? `${site.uptime_latency_ms} ms` : "—"}
          />
          <Item label="Server" value={site.server_label || site.server_id} />
          <Item label="Container" value={site.service_name || "Not linked"} mono />
          <Item label="Environment" value={site.environment || "production"} />
        </dl>

        <div className="mt-5 flex flex-wrap gap-2">
          {site.url && (
            <ActionBtn onClick={probe} disabled={!!actionBusy} loading={actionBusy === "probe"}>
              Check now
            </ActionBtn>
          )}
          {site.service_name && (
            <ActionBtn
              onClick={() => (isProd ? setConfirmRestart(true) : restart())}
              disabled={!!actionBusy}
              loading={actionBusy === "restart"}
              variant="warn"
            >
              Restart
            </ActionBtn>
          )}
          {site.service_name && (
            <ActionBtn onClick={loadLogs} disabled={logsLoading}>
              {logsLoading ? "Loading…" : "Refresh logs"}
            </ActionBtn>
          )}
        </div>

        {confirmRestart && (
          <div className="mt-4 rounded-lg border border-amber-500/25 bg-amber-500/5 p-3 text-sm">
            <p className="text-amber-100">Restart production container?</p>
            <div className="mt-2 flex gap-2">
              <button type="button" className="btn-primary text-xs" onClick={restart}>
                Confirm
              </button>
              <button type="button" className="btn-ghost text-xs" onClick={() => setConfirmRestart(false)}>
                Cancel
              </button>
            </div>
          </div>
        )}

        {message && <p className="mt-3 text-sm text-mint">{message}</p>}
        {error && <p className="mt-3 text-sm text-red-400">{error}</p>}

        {site.service_name ? (
          <div className="mt-6">
            <p className="mb-2 text-xs font-medium text-zinc-500">Container logs</p>
            <pre className="max-h-80 overflow-auto rounded-lg border border-surface-border bg-black/50 p-3 font-mono text-[11px] leading-relaxed text-zinc-400">
              {logsLoading ? "Loading…" : logs || "No output"}
            </pre>
          </div>
        ) : (
          <p className="mt-6 text-xs text-zinc-600">
            Link a container name when adding the site to enable logs and restart.
          </p>
        )}
      </div>

      <footer className="shrink-0 border-t border-surface-border px-5 py-3">
        <button type="button" onClick={remove} disabled={!!actionBusy} className="btn-danger-ghost text-xs">
          Remove site
        </button>
      </footer>
    </>
  );

  if (embedded) {
    return <div className="flex h-full min-h-0 flex-col">{inner}</div>;
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end md:hidden">
      <button type="button" className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} aria-label="Close" />
      <aside className="relative flex h-full w-full max-w-md flex-col bg-surface-raised shadow-modal">
        {inner}
      </aside>
    </div>
  );
}

function Item({ label, value, highlight, mono }) {
  return (
    <div>
      <dt className="text-[11px] font-medium uppercase tracking-wide text-zinc-600">{label}</dt>
      <dd
        className={`mt-0.5 truncate text-sm ${mono ? "font-mono text-xs" : ""} ${
          highlight ? "text-red-300" : "text-zinc-200"
        }`}
      >
        {value}
      </dd>
    </div>
  );
}

function ActionBtn({ children, onClick, disabled, loading, variant }) {
  const cls = variant === "warn" ? "btn-secondary border-amber-500/30 text-amber-100" : "btn-secondary";
  return (
    <button type="button" onClick={onClick} disabled={disabled || loading} className={`${cls} text-xs`}>
      {loading ? "…" : children}
    </button>
  );
}
