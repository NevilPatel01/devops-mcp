import { useState } from "react";
import { send } from "../ws.js";

const riskStyles = {
  low: "border-emerald-700 bg-emerald-900/40 text-emerald-100",
  medium: "border-amber-700 bg-amber-900/40 text-amber-100",
  high: "border-red-700 bg-red-900/40 text-red-100",
};

export default function ApprovalCard({ action, onClear }) {
  const [confirmText, setConfirmText] = useState("");
  const [feedback, setFeedback] = useState("");
  const [showReject, setShowReject] = useState(false);
  const [busy, setBusy] = useState(false);

  if (!action) return null;

  const risk = (action.risk_tier || "medium").toLowerCase();
  const isHigh = risk === "high";
  const canApprove = !isHigh || confirmText.trim().toUpperCase() === "CONFIRM";
  const params = action.parameters || {};

  const approve = () => {
    setBusy(true);
    send({
      type: "approve_action",
      action_id: action.id,
      confirm_text: isHigh ? confirmText : undefined,
    });
    onClear?.();
  };

  const reject = () => {
    setBusy(true);
    send({
      type: "reject_action",
      action_id: action.id,
      feedback: feedback || "Rejected by operator",
    });
    onClear?.();
  };

  return (
    <section
      className={`rounded-xl border p-5 shadow-lg ${riskStyles[risk] || riskStyles.medium}`}
      role="alert"
    >
      <motionHeader risk={risk} />
      <p className="mt-2 text-sm">{action.description}</p>
      <p className="mt-2 text-xs opacity-90">
        <span className="font-medium">Rationale:</span> {action.rationale}
      </p>
      <p className="mt-1 text-xs opacity-75">
        <span className="font-medium">Rollback:</span> {action.rollback_plan}
      </p>
      <p className="mt-2 font-mono text-xs opacity-70">
        {params.server_id} · {params.container_name || params.service_name || action.action_type}
      </p>

      {isHigh && (
        <div className="mt-3">
          <label className="text-xs opacity-80">Type CONFIRM to approve HIGH risk</label>
          <input
            type="text"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            className="mt-1 w-full rounded border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            placeholder="CONFIRM"
          />
        </div>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={busy || !canApprove}
          onClick={approve}
          className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-40"
        >
          Approve
        </button>
        {!showReject ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => setShowReject(true)}
            className="rounded-lg bg-red-800 px-4 py-2 text-sm font-medium text-red-50 hover:bg-red-700 disabled:opacity-40"
          >
            Reject
          </button>
        ) : (
          <div className="flex w-full flex-col gap-2 sm:flex-row sm:items-end">
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="Why reject? (saved as feedback rule)"
              className="min-h-[60px] flex-1 rounded border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            />
            <button
              type="button"
              disabled={busy}
              onClick={reject}
              className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-500 disabled:opacity-40"
            >
              Confirm reject
            </button>
          </div>
        )}
      </div>
    </section>
  );
}

function motionHeader({ risk }) {
  return (
    <motionHeaderInner>
      <h2 className="text-lg font-semibold">Action pending approval</h2>
      <span className="rounded-full border border-current px-2 py-0.5 text-xs uppercase">
        {risk}
      </span>
    </motionHeaderInner>
  );
}

function motionHeaderInner({ children }) {
  return <div className="flex items-center justify-between gap-2">{children}</div>;
}
