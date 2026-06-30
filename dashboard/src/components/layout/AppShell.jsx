import { useEffect, useState } from "react";
import { connect, getStatus } from "../../ws.js";

const NAV = [
  { id: "sites", label: "Fleet" },
  { id: "overview", label: "Alerts" },
  { id: "incidents", label: "Incidents" },
  { id: "settings", label: "Settings" },
];

export default function AppShell({ view, onNavigate, children, stats, actions }) {
  const ws = getStatus();
  const alertCount = (stats?.sites_down ?? 0) + (stats?.open_incidents ?? 0);

  return (
    <div className="flex min-h-screen flex-col bg-surface">
      {/* Top header */}
      <header className="sticky top-0 z-40 border-b border-surface-border bg-surface-raised/95 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3 sm:px-6">
          <button
            type="button"
            onClick={() => onNavigate("sites")}
            className="flex shrink-0 items-center gap-2.5 text-left"
          >
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-white text-xs font-bold text-zinc-950">
              DM
            </div>
            <div className="hidden sm:block">
              <p className="text-sm font-semibold tracking-tight text-white">DevOps MCP</p>
              <p className="text-[10px] text-zinc-500">Multi-site fleet</p>
            </div>
          </button>

          <nav className="flex flex-1 items-center gap-1 overflow-x-auto">
            {NAV.map((item) => {
              const active = view === item.id;
              const badge =
                item.id === "overview"
                  ? alertCount
                  : item.id === "incidents"
                    ? stats?.open_incidents
                    : 0;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => onNavigate(item.id)}
                  className={`relative shrink-0 rounded-lg px-3 py-2 text-sm transition ${
                    active
                      ? "bg-white/10 font-medium text-white"
                      : "text-zinc-500 hover:bg-white/5 hover:text-zinc-200"
                  }`}
                  aria-current={active ? "page" : undefined}
                >
                  {item.label}
                  {badge > 0 && (
                    <span className="ml-1.5 inline-flex min-w-[1.125rem] items-center justify-center rounded bg-red-500/20 px-1 text-[10px] font-semibold text-red-400">
                      {badge}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>

          {actions && <div className="hidden shrink-0 items-center gap-2 sm:flex">{actions}</div>}
        </div>

        {/* Live fleet strip — visible on Fleet view */}
        {view === "sites" && stats && (
          <div className="border-t border-surface-border/60 bg-black/20">
            <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2 text-xs sm:px-6">
              <LiveStat label="Sites" value={stats.sites_total ?? 0} />
              <LiveStat label="Up" value={stats.sites_up ?? 0} tone="up" />
              <LiveStat label="Down" value={stats.sites_down ?? 0} tone="down" />
              <span className="hidden h-3 w-px bg-surface-border sm:block" />
              <span className="text-zinc-500">
                Checks every <span className="text-zinc-300">60s</span>
              </span>
              <span className="flex items-center gap-1.5 text-zinc-500">
                <span className={`status-dot ${ws === "open" ? "bg-mint animate-pulse" : "bg-zinc-600"}`} />
                {ws === "open" ? "Live updates" : "Reconnecting…"}
              </span>
            </div>
          </div>
        )}
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6">{children}</main>
    </div>
  );
}

function LiveStat({ label, value, tone }) {
  const color =
    tone === "up" ? "text-emerald-400" : tone === "down" ? "text-red-400" : "text-zinc-100";
  return (
    <span className="flex items-center gap-1.5 tabular-nums">
      <span className={`text-sm font-semibold ${color}`}>{value}</span>
      <span className="text-zinc-600">{label}</span>
    </span>
  );
}

export function useFleetStats() {
  const [stats, setStats] = useState(null);

  const refresh = () => {
    fetch("/api/fleet/overview")
      .then((r) => r.json())
      .then((d) => d.success && setStats(d.stats))
      .catch(() => {});
  };

  useEffect(() => {
    connect();
    refresh();
    const id = setInterval(refresh, 15_000);
    return () => clearInterval(id);
  }, []);

  return { stats, refreshStats: refresh };
}
