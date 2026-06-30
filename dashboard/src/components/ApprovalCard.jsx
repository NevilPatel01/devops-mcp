import { useState } from "react";
import { send } from "../ws.js";

const riskStyles = {
  low: "border-emerald-700 bg-emerald-900/40 text-emerald-100",
  medium: "border-amber-700 bg-amber-900/40 text-amber-100",
  high: "border-red-700 bg-red-900/40 text-red-100",
};

export default function ApprovalCard({ action, onClear }) {
  const [confirmText, setConfirmText] = useState("");
  const [complianceText, setComplianceText] = useState("");
  const [feedback, setFeedback] = useState("");
  const [showReject, setShowReject] = useState(false);
  const [busy, setBusy] = useState(false);

  if (!action) return null;

  const risk = (action.risk_tier || "medium").toLowerCase();
  const isHigh = risk === "high";
  const complianceSensitive = Boolean(action.compliance_sensitive);
  const needsComplianceAck =
    complianceSensitive && (action.requires_compliance_ack || (isHigh && complianceSensitive));
  const confirmOk = !isHigh || confirmText.trim().toUpperCase() === "CONFIRM";
  const complianceOk =
    !needsComplianceAck || complianceText.trim().toUpperCase() === "COMPLIANCE";
  const canApprove = confirmOk && complianceOk;
  const params = action.parameters || {};

  const approve = () => {
    setBusy(true);
    send({
      type: "approve_action",
      action_id: action.id,
      confirm_text: isHigh ? confirmText : undefined,
      compliance_confirm_text: needsComplianceAck ? complianceText : undefined,
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
      className={`rounded-xl border p-4 ${riskStyles[risk] || riskStyles.medium}`}
      role="alert"
    >
      <motionHeader risk={risk} />
      {complianceSensitive && (
        <p className="mt-2 rounded-lg border border-amber-600/60 bg-amber-950/50 px-3 py-2 text-sm text-amber-100">
          {action.compliance_message ||
            "Compliance-regulated service — review audit impact before approving."}
          {action.compliance_profile && action.compliance_profile !== "none" && (
            <span className="ml-2 text-xs uppercase opacity-80">
              ({action.compliance_profile})
            </span>
          )}
        </p>
      )}
      <p className="mt-2 text-sm text-current">{action.description}</p>
      <p className="mt-2 text-xs text-current/90">
        <span className="font-medium">Rationale:</span> {action.rationale}
      </p>
      <p className="mt-1 text-xs text-current/80">
        <span className="font-medium">Rollback:</span> {action.rollback_plan}
      </p>
      <p className="mt-2 font-mono text-xs text-current/75">
        {params.server_id} · {params.container_name || params.service_name || action.action_type}
      </p>

      {isHigh && (
        <motionHeaderInner>
          <label className="w-full text-xs text-current/80">Type CONFIRM to approve HIGH risk</label>
          <input
            type="text"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            className="mt-1 w-full rounded border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            placeholder="CONFIRM"
          />
        </motionHeaderInner>
      )}

      {needsComplianceAck && (
        <motionHeaderInner>
          <label className="w-full text-xs text-amber-200/90">
            Type COMPLIANCE to acknowledge compliance impact
          </label>
          <input
            type="text"
            value={complianceText}
            onChange={(e) => setComplianceText(e.target.value)}
            className="mt-1 w-full rounded border border-amber-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            placeholder="COMPLIANCE"
          />
        </motionHeaderInner>
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
    <div className="flex items-center justify-between gap-2">
      <h2 className="text-lg font-semibold text-current">Action pending approval</h2>
      <span className="rounded-full border border-current px-2 py-0.5 text-xs uppercase">
        {risk}
      </span>
    </div>
  );
}

function motionHeaderInner({ children }) {
  return <div className="mt-3 flex flex-col gap-1">{children}</div>;
}
