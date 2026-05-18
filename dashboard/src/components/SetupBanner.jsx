import { useCallback, useEffect, useState } from "react";
import { fetchJson } from "../api.js";

const DISMISS_KEY = "devops-setup-banner-dismissed";

function missingItems(status) {
  if (!status) return [];
  const items = [];
  if (!status.servers_configured) {
    items.push({
      id: "servers",
      label: "Server config",
      hint: "cp config/servers.yaml.example → config/servers.yaml and add your VPS hosts",
    });
  }
  if (!status.repos_configured || status.repos_count === 0) {
    items.push({
      id: "repos",
      label: "Repos config",
      hint: "cp config/repos.yaml.example → config/repos.yaml and link repos to servers",
    });
  }
  if (!status.anthropic_configured) {
    items.push({
      id: "anthropic",
      label: "Anthropic API key",
      hint: "Set ANTHROPIC_API_KEY in .env (copy from .env.example)",
    });
  }
  if (!status.github_configured) {
    items.push({
      id: "github",
      label: "GitHub token",
      hint: "Set GITHUB_TOKEN in .env for CI/CD correlation and rollback",
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
        className="mb-4 w-full rounded-lg border border-dashed border-slate-700 bg-slate-900/40 px-3 py-2 text-left text-xs text-slate-500 hover:border-slate-600 hover:text-slate-400"
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
    <section
      className="mb-6 rounded-xl border border-amber-800/60 bg-gradient-to-br from-amber-950/40 to-slate-900/80 p-4 shadow-lg"
      role="status"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-amber-100">Setup checklist</h2>
          <p className="text-xs text-slate-400">
            Phase {status.phase} — finish these before full agent features work
          </p>
        </div>
        <button
          type="button"
          onClick={dismiss}
          className="shrink-0 text-xs text-slate-500 hover:text-slate-300"
        >
          Dismiss
        </button>
      </div>
      <ul className="mt-3 space-y-2">
        {gaps.map((item) => (
          <li
            key={item.id}
            className="rounded-lg border border-slate-800/80 bg-slate-950/50 px-3 py-2"
          >
            <p className="text-sm font-medium text-amber-100">{item.label}</p>
            <p className="mt-0.5 font-mono text-xs text-slate-400">{item.hint}</p>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-slate-500">
        Verify with{" "}
        <code className="rounded bg-slate-800 px-1 text-slate-300">
          curl localhost:8080/api/setup/status
        </code>
      </p>
    </section>
  );
}
