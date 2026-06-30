const STATUS = {
  up: { badge: "badge-up", dot: "bg-emerald-400" },
  down: { badge: "badge-down", dot: "bg-red-400" },
  degraded: { badge: "badge bg-amber-500/10 text-amber-400", dot: "bg-amber-400" },
  unknown: { badge: "badge-unknown", dot: "bg-zinc-500" },
};

export default function SiteCard({ site, onClick, selected, compact }) {
  const status = site.uptime_status || site.status || "unknown";
  const s = STATUS[status] || STATUS.unknown;

  return (
    <button
      type="button"
      onClick={() => onClick?.(site)}
      className={`group w-full text-left transition ${
        compact
          ? `border-b border-surface-border px-4 py-3 hover:bg-white/[0.02] ${
              selected ? "bg-white/[0.04]" : ""
            }`
          : `panel p-4 hover:border-zinc-600 ${selected ? "border-zinc-500 ring-1 ring-white/10" : ""}`
      }`}
    >
      <div className="flex items-start gap-3">
        <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${s.dot}`} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="truncate font-medium text-zinc-100">{site.name}</p>
            {site.environment === "production" && (
              <span className="shrink-0 rounded px-1 py-0.5 text-[9px] font-medium uppercase tracking-wider text-amber-500/90">
                prod
              </span>
            )}
          </div>
          <p className="mt-0.5 truncate text-xs text-zinc-500">
            {site.client_name || site.url || site.server_label || site.server_id}
          </p>
          {!compact && (
            <div className="mt-2 flex flex-wrap gap-3 text-xs text-zinc-600">
              {site.uptime_latency_ms != null && <span>{site.uptime_latency_ms} ms</span>}
              {site.uptime_status_code != null && <span>HTTP {site.uptime_status_code}</span>}
            </div>
          )}
        </div>
        <span className={s.badge}>{status}</span>
      </div>
      {compact && site.uptime_latency_ms != null && (
        <p className="mt-1 pl-5 text-[11px] tabular-nums text-zinc-600">{site.uptime_latency_ms} ms</p>
      )}
    </button>
  );
}
