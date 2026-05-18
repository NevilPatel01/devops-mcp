import { useEffect, useState } from "react";
import ServerSparkline from "./ServerSparkline.jsx";

const statusColors = {
  healthy: "bg-emerald-900/60 text-emerald-300",
  degraded: "bg-amber-900/60 text-amber-300",
  critical: "bg-red-900/60 text-red-300",
  unknown: "bg-slate-700 text-slate-300",
};

function formatPct(value) {
  if (value == null || Number.isNaN(value)) return "—";
  return `${Number(value).toFixed(1)}%`;
}

export default function ServerGrid({ servers = [] }) {
  const [selectedId, setSelectedId] = useState(null);
  const [serviceMeta, setServiceMeta] = useState({});
  const selected = servers.find((s) => s.server_id === selectedId);

  useEffect(() => {
    fetch("/api/config/services")
      .then((r) => r.json())
      .then((data) => {
        if (!data.success) return;
        const map = {};
        for (const srv of data.servers || []) {
          map[srv.server_id] = srv.services || [];
        }
        setServiceMeta(map);
      })
      .catch(() => {});
  }, []);

  if (servers.length === 0) {
    return (
      <section className="rounded-xl border border-slate-800 bg-slate-900/50 p-6">
        <h2 className="text-lg font-semibold text-slate-200">Servers</h2>
        <p className="mt-2 text-sm text-slate-400">
          Connecting to poller… Live metrics appear within ~30s for configured hosts.
        </p>
      </section>
    );
  }

  return (
    <section className="space-y-4">
      <h2 className="text-lg font-semibold text-slate-200">Servers</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        {servers.map((s) => {
          const id = s.server_id;
          const isSelected = selectedId === id;
          const badge = statusColors[s.status] || statusColors.unknown;
          return (
            <article
              key={id}
              role="button"
              tabIndex={0}
              onClick={() => setSelectedId(isSelected ? null : id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setSelectedId(isSelected ? null : id);
                }
              }}
              className={`cursor-pointer rounded-xl border p-4 transition-colors ${
                isSelected
                  ? "border-sky-500 bg-slate-900/80 ring-1 ring-sky-500/40"
                  : "border-slate-800 bg-slate-900/50 hover:border-slate-600"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <h3 className="font-medium text-slate-100">{s.label || id}</h3>
                <span className={`rounded-full px-2 py-0.5 text-xs uppercase ${badge}`}>
                  {s.status || "unknown"}
                </span>
              </div>
              <p className="mt-1 text-xs text-slate-500">{id}</p>
              <dl className="mt-3 grid grid-cols-4 gap-2 text-sm text-slate-400">
                <div>
                  <dt className="text-xs">CPU</dt>
                  <dd className="text-slate-200">{formatPct(s.cpu_percent)}</dd>
                </div>
                <div>
                  <dt className="text-xs">Mem</dt>
                  <dd className="text-slate-200">{formatPct(s.memory_percent)}</dd>
                </div>
                <div>
                  <dt className="text-xs">Disk</dt>
                  <dd className="text-slate-200">{formatPct(s.disk_percent)}</dd>
                </div>
                <div>
                  <dt className="text-xs">Containers</dt>
                  <dd className="text-slate-200">{s.container_count ?? s.containers?.length ?? 0}</dd>
                </div>
              </dl>
              {s.error && (
                <p className="mt-2 text-xs text-red-400">{s.error}</p>
              )}
              {s.captured_at && (
                <p className="mt-2 text-xs text-slate-600">
                  Updated {new Date(s.captured_at).toLocaleString()}
                </p>
              )}
            </article>
          );
        })}
      </div>

      {selected && (
        <div className="rounded-xl border border-slate-700 bg-slate-900/60 p-4">
          <h3 className="text-sm font-medium text-slate-300">
            Containers — {selected.label || selected.server_id}
          </h3>
          {(serviceMeta[selected.server_id] || []).some((s) => s.sensitive) && (
            <p className="mt-2 text-xs text-amber-300/90">
              Sensitive services:{" "}
              {(serviceMeta[selected.server_id] || [])
                .filter((s) => s.sensitive)
                .map((s) => s.name)
                .join(", ")}
            </p>
          )}
          {!selected.containers?.length ? (
            <p className="mt-2 text-sm text-slate-500">No container data yet.</p>
          ) : (
            <ul className="mt-3 divide-y divide-slate-800">
              {selected.containers.map((c) => {
                const cfgSvc = (serviceMeta[selected.server_id] || []).find(
                  (s) =>
                    c.name?.toLowerCase().includes(s.name.toLowerCase()) ||
                    s.name.toLowerCase().includes((c.name || "").toLowerCase())
                );
                return (
                  <li
                    key={c.name}
                    className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm"
                  >
                    <span className="font-mono text-slate-200">
                      {c.name}
                      {cfgSvc?.sensitive && (
                        <span className="ml-2 rounded bg-amber-900/40 px-1 text-[10px] text-amber-300">
                          sensitive
                        </span>
                      )}
                    </span>
                    <span className="text-slate-400">{c.status}</span>
                    <span className="w-full truncate text-xs text-slate-500">{c.image}</span>
                  </li>
                );
              })}
            </ul>
          )}
          <ServerSparkline serverId={selected.server_id} />
        </div>
      )}
    </section>
  );
}
