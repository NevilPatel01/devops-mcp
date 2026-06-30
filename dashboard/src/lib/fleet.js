export function timeAgo(iso) {
  if (!iso) return "Never checked";
  const sec = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (sec < 0) return "Just now";
  if (sec < 10) return "Just now";
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return new Date(iso).toLocaleString();
}

export function sortSitesByUrgency(sites) {
  const rank = (s) => {
    const st = s.uptime_status || s.status || "unknown";
    if (st === "down") return 0;
    if (st === "degraded") return 1;
    if (st === "unknown") return 2;
    return 3;
  };
  return [...sites].sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
}

export function avgLatency(sites) {
  const vals = sites.map((s) => s.uptime_latency_ms).filter((v) => v != null);
  if (!vals.length) return null;
  return Math.round(vals.reduce((a, b) => a + b, 0) / vals.length);
}
