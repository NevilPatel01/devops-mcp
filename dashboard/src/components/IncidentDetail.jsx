import { useCallback, useEffect, useState } from "react";

function httpErrorMessage(res, text) {
  return res.status === 404
    ? "API not found — restart python server.py (old process may still be on port 8080)"
    : `HTTP ${res.status}: ${text.slice(0, 120)}`;
}

export default function IncidentDetail({ incident, onClose, onFalsePositiveMarked }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [draftPmLoading, setDraftPmLoading] = useState(false);
  const [falsePositiveLoading, setFalsePositiveLoading] = useState(false);
  const [compliance, setCompliance] = useState(null);
  const [fpReason, setFpReason] = useState("");
  const [suppressSimilar, setSuppressSimilar] = useState(true);
  const [runbookLoading, setRunbookLoading] = useState(false);
  const [runbookMsg, setRunbookMsg] = useState(null);

  const loadDetail = useCallback(async () => {
    if (!incident?.id) return;
    setLoading(true);
    setError(null);
    setDetail(null);
    try {
      const res = await fetch(`/api/incidents/${incident.id}`);
      if (!res.ok) {
        const text = await res.text();
        setError(httpErrorMessage(res, text));
        return;
      }
      const data = await res.json();
      if (data.success) {
        setDetail(data);
        const cRes = await fetch(`/api/incidents/${incident.id}/compliance`);
        if (cRes.ok) {
          const cData = await cRes.json();
          if (cData.success) setCompliance(cData);
        }
      } else setError(data.error || "Failed to load incident");
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [incident?.id]);

  useEffect(() => {
    if (!incident?.id) return undefined;
    loadDetail();
    return undefined;
  }, [incident?.id, loadDetail]);

  if (!incident) return null;
  const postmortem = detail?.incident?.postmortem_draft;

  const draftPm = async () => {
    setDraftPmLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/incidents/${incident.id}/postmortem`, { method: "POST" });
      if (!res.ok) {
        const text = await res.text();
        setError(httpErrorMessage(res, text));
        return;
      }
      const data = await res.json();
      if (data.success && detail) {
        setDetail({
          ...detail,
          incident: { ...detail.incident, postmortem_draft: data.postmortem_markdown },
        });
      } else {
        setError(data.error || "Failed to draft postmortem");
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setDraftPmLoading(false);
    }
  };

  const markFalsePositive = async () => {
    setFalsePositiveLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/incidents/${incident.id}/false-positive`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          reason: fpReason.trim() || undefined,
          suppress_similar_hours: suppressSimilar ? 24 : 0,
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        setError(httpErrorMessage(res, text));
        return;
      }
      const data = await res.json();
      if (data.success) {
        onFalsePositiveMarked?.(data);
        onClose?.();
      } else {
        setError(data.error || "Failed to mark false positive");
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setFalsePositiveLoading(false);
    }
  };

  const generateRunbook = async () => {
    setRunbookLoading(true);
    setRunbookMsg(null);
    setError(null);
    try {
      const res = await fetch(`/api/incidents/${incident.id}/generate-runbook`, {
        method: "POST",
      });
      const data = await res.json();
      if (data.success) {
        setRunbookMsg(`Draft runbook ${data.runbook?.runbook_id || "created"}`);
      } else {
        setError(data.error || "Failed to generate runbook");
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setRunbookLoading(false);
    }
  };

  const overlayClass =
    "fixed inset-0 z-40 flex items-center justify-center bg-black/50 p-4";
  const panelClass =
    "max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-xl border border-slate-700 bg-slate-900 p-6";

  return (
    <div className={overlayClass} onClick={onClose}>
      <div
        role="dialog"
        className={panelClass}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-100">{incident.title}</h2>
            <p className="mt-1 text-sm text-slate-500">
              {incident.server_id} · {incident.service_name || "—"} · {incident.status}
              {(detail?.incident?.is_sensitive || incident.is_sensitive) ? (
                <span className="ml-2 rounded bg-amber-900/50 px-2 py-0.5 text-xs text-amber-200">
                  sensitive
                </span>
              ) : null}
            </p>
          </div>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-white">
            Close
          </button>
        </div>
        {loading && <p className="mt-4 text-sm text-slate-500">Loading detail…</p>}
        {error && <p className="mt-4 text-sm text-red-400">{error}</p>}
        {detail && (
          <>
            <p className="mt-4 text-sm text-slate-300">{detail.incident?.description}</p>
            {detail.actions?.length > 0 && (
              <section className="mt-4">
                <h3 className="text-sm font-medium text-slate-400">Actions</h3>
                <ul className="mt-2 space-y-2 text-sm">
                  {detail.actions.map((a) => (
                    <li key={a.id} className="rounded border border-slate-800 p-2">
                      <span className="text-slate-200">{a.description}</span>
                      <span className="ml-2 text-xs text-slate-500">{a.status}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {(compliance?.is_sensitive || detail?.incident?.is_sensitive) && (
              <section className="mt-4 rounded-lg border border-amber-800/50 bg-amber-950/20 p-3">
                <h3 className="text-sm font-medium text-amber-200">Compliance impact</h3>
                <p className="mt-1 text-xs text-amber-100/90">
                  Profile:{" "}
                  {compliance?.compliance_profile ||
                    detail?.incident?.compliance_profile ||
                    "none"}
                  . Review audit trail and postmortem Compliance impact section before closing.
                </p>
                {compliance?.audit_trail?.length > 0 && (
                  <ul className="mt-2 max-h-32 space-y-1 overflow-y-auto text-xs text-slate-400">
                    {compliance.audit_trail.slice(0, 8).map((e) => (
                      <li key={e.id}>
                        {e.event_type} · {e.actor || "system"} ·{" "}
                        {e.timestamp && new Date(e.timestamp).toLocaleString()}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )}
            {(incident.status === "resolved" || detail?.incident?.status === "resolved") && (
              <section className="mt-4 flex items-center gap-3">
                <button
                  type="button"
                  onClick={generateRunbook}
                  disabled={runbookLoading}
                  className="rounded-lg border border-cyan-800/60 bg-cyan-950/30 px-3 py-1.5 text-xs text-cyan-300 hover:bg-cyan-900/40 disabled:opacity-50"
                >
                  {runbookLoading ? "Generating…" : "Generate runbook"}
                </button>
                {runbookMsg && (
                  <span className="text-xs text-emerald-400">{runbookMsg}</span>
                )}
              </section>
            )}
            <section className="mt-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-medium text-slate-400">Postmortem</h3>
                <button
                  type="button"
                  onClick={draftPm}
                  disabled={draftPmLoading}
                  className="text-xs text-sky-400 hover:text-sky-300 disabled:opacity-50"
                >
                  {draftPmLoading ? "Drafting…" : "Draft with Claude"}
                </button>
              </div>
              {postmortem ? (
                <pre className="mt-2 whitespace-pre-wrap rounded bg-slate-950 p-3 text-xs text-slate-300">
                  {postmortem}
                </pre>
              ) : (
                <p className="mt-2 text-xs text-slate-600">No postmortem yet.</p>
              )}
            </section>
            <section className="mt-4 rounded-lg border border-slate-700 p-3">
              <h3 className="text-sm font-medium text-slate-400">False positive</h3>
              <label className="mt-2 block text-xs text-slate-500">
                Reason (optional)
                <input
                  type="text"
                  value={fpReason}
                  onChange={(e) => setFpReason(e.target.value)}
                  className="mt-1 w-full rounded border border-slate-600 bg-slate-950 px-2 py-1.5 text-sm text-slate-200"
                  placeholder="e.g. expected deploy spike"
                />
              </label>
              <label className="mt-2 flex items-center gap-2 text-xs text-slate-400">
                <input
                  type="checkbox"
                  checked={suppressSimilar}
                  onChange={(e) => setSuppressSimilar(e.target.checked)}
                />
                Suppress similar alerts for 24h
              </label>
              <button
                type="button"
                onClick={markFalsePositive}
                disabled={falsePositiveLoading}
                className="mt-3 rounded border border-slate-600 px-3 py-1.5 text-xs text-slate-300 disabled:opacity-50"
              >
                {falsePositiveLoading ? "Marking…" : "Mark false positive"}
              </button>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
