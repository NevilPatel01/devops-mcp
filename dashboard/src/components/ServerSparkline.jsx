import { useEffect, useState } from "react";
import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const METRICS = [
  { key: "cpu", label: "CPU", color: "#38bdf8" },
  { key: "mem", label: "Memory", color: "#a78bfa" },
  { key: "disk", label: "Disk", color: "#fbbf24" },
];

export default function ServerSparkline({ serverId }) {
  const [points, setPoints] = useState([]);
  const [active, setActive] = useState(() => new Set(["cpu", "mem"]));

  useEffect(() => {
    if (!serverId) return undefined;
    fetch(`/api/servers/${serverId}/snapshots?limit=48`)
      .then((r) => r.json())
      .then((data) => {
        if (data.success) {
          setPoints(
            (data.snapshots || []).map((s) => ({
              t: s.captured_at ? new Date(s.captured_at).toLocaleTimeString() : "",
              cpu: s.cpu_percent ?? 0,
              mem: s.memory_percent ?? 0,
              disk: s.disk_percent ?? 0,
            }))
          );
        }
      });
  }, [serverId]);

  const toggle = (key) => {
    setActive((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        if (next.size > 1) next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  if (!serverId || points.length < 2) return null;

  return (
    <div className="mt-4 h-44 rounded-lg border border-slate-800 bg-slate-950/50 p-2">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-slate-500">Metrics trend (click legend)</p>
        <div className="flex gap-1">
          {METRICS.map((m) => (
            <button
              key={m.key}
              type="button"
              onClick={() => toggle(m.key)}
              className={`rounded px-2 py-0.5 text-xs transition-opacity ${
                active.has(m.key) ? "opacity-100" : "opacity-35"
              }`}
              style={{
                color: m.color,
                backgroundColor: active.has(m.key) ? `${m.color}22` : "transparent",
              }}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>
      <ResponsiveContainer width="100%" height="78%">
        <LineChart data={points}>
          <XAxis dataKey="t" hide />
          <YAxis domain={[0, 100]} width={28} tick={{ fontSize: 10 }} />
          <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} />
          {METRICS.filter((m) => active.has(m.key)).map((m) => (
            <Line
              key={m.key}
              type="monotone"
              dataKey={m.key}
              name={m.label}
              stroke={m.color}
              dot={false}
              strokeWidth={2}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
