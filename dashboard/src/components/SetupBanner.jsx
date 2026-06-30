import { useCallback, useEffect, useState } from "react";
import { fetchJson } from "../api.js";

const DISMISS_KEY = "devops-setup-banner-dismissed";

function missingItems(status) {
  if (!status) return [];
  const items = [];
  if ((status.servers_in_db ?? 0) === 0 && !status.servers_configured) {
    items.push({
      id: "servers",
      label: "Connect a VPS",
      hint: "Fleet → Add server (SSH key or upload)",
    });
  }
  if ((status.sites_count ?? 0) === 0) {
    items.push({
      id: "sites",
      label: "Add a client site",
      hint: "Fleet → Add site with URL for live uptime monitoring",
    });
  }
  if (!status.anthropic_configured) {
    items.push({
      id: "anthropic",
      label: "AI optional",
      hint: "Settings → Anthropic key for auto-remediation (monitoring works without it)",
    });
  }
  if (!status.dashboard_built) {
    items.push({
      id: "dashboard",
      label: "Dashboard build",
      hint: "cd dashboard && npm install && npm run build",
    });
  }
  return items;
}

export default function SetupBanner() {
  const [status, setStatus] = useState(null);
  const [collapsed, setCollapsed] = useState(
    () => typeof window !== "undefined" && sessionStorage.getItem(DISMISS_KEY) === "1"
  );

  const load = useCallback(async () => {
    const result = await fetchJson("/api/setup/status");
    if (result.ok && result.data) {
      setStatus(result.data);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, [load]);

  const gaps = missingItems(status);
  if (!status || gaps.length === 0) {
    return null;
  }

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={() => setCollapsed(false)}
        className="w-full rounded-xl border border-dashed border-surface-border bg-surface-overlay/40 px-4 py-2.5 text-left text-xs text-slate-500 transition hover:border-accent/30 hover:text-slate-300"
      >
        Setup incomplete — show checklist ({gaps.length} item{gaps.length === 1 ? "" : "s"})
      </button>
    );
  }

  const dismiss = () => {
    setCollapsed(true);
    sessionStorage.setItem(DISMISS_KEY, "1");
  };

  return (
    <section className="glass-panel border-amber-500/20 p-5" role="status">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-amber-200">Getting started</h2>
          <p className="text-xs text-slate-500">Complete these steps to monitor your fleet</p>
        </div>
        <button type="button" onClick={dismiss} className="text-xs text-slate-500 hover:text-slate-300">
          Dismiss
        </button>
      </div>
      <ul className="mt-4 space-y-2">
        {gaps.map((item) => (
          <li
            key={item.id}
            className="rounded-xl border border-surface-border/80 bg-surface/60 px-4 py-3"
          >
            <p className="text-sm font-medium text-slate-200">{item.label}</p>
            <p className="mt-0.5 text-xs text-slate-500">{item.hint}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
