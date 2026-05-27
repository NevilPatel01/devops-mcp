"""Runbook matching, classification, and draft generation."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any

from compliance import bump_risk_for_sensitive, is_sensitive_service
from db import store
from models.config import RunbooksConfig, load_rules_config
from models.incident import ProposedAction

logger = logging.getLogger(__name__)


def classify_incident_type(
    reason: str,
    correlation: dict[str, Any] | None = None,
) -> str:
    """Map anomaly text to a stable incident_type for runbook matching."""
    text = (reason or "").lower()
    if correlation and correlation.get("related_deploy"):
        return "deploy_failure"
    if any(k in text for k in ("exited", "exit code", "not running", "unhealthy")):
        return "container_exited"
    if "restart" in text and ("count" in text or "restarts" in text):
        return "container_restart_storm"
    if "cpu" in text:
        return "high_cpu"
    if "memory" in text or "mem" in text:
        return "high_memory"
    if "disk" in text:
        return "high_disk"
    return "unknown"


def incident_signature(
    incident_type: str,
    service_name: str | None,
    action_type: str,
) -> str:
    raw = f"{incident_type}|{service_name or ''}|{action_type}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def steps_to_proposed_action(
    steps: list[dict[str, Any]],
    *,
    incident_id: str,
    server_id: str,
    service_name: str | None,
) -> dict[str, Any] | None:
    """Convert first runbook step to an agent proposal dict (v1 single step)."""
    if not steps:
        return None
    ordered = sorted(steps, key=lambda s: int(s.get("order", 1)))
    step = ordered[0]
    params = dict(step.get("parameters") or {})
    params.setdefault("server_id", server_id)
    if service_name:
        params.setdefault("service_name", service_name)
    return {
        "action_type": step.get("action_type", "restart_container"),
        "description": step.get("description", "Runbook remediation"),
        "rationale": step.get(
            "expected_outcome",
            "Matched approved runbook for this incident type.",
        ),
        "risk_tier": "low",
        "rollback_plan": "Re-run previous compose state or manual rollback.",
        "parameters": params,
    }


def _runbooks_config() -> RunbooksConfig:
    try:
        return load_rules_config().runbooks
    except (FileNotFoundError, OSError):
        return RunbooksConfig()


async def draft_runbook_from_incident(incident_id: str) -> dict[str, Any]:
    """Build a draft runbook from a resolved incident's last successful action."""
    incident = await store.get_incident(incident_id)
    if not incident:
        return {"success": False, "error": "Incident not found"}
    actions = await store.get_actions_for_incident(incident_id)
    executed = [a for a in actions if a.get("status") == "executed"]
    if not executed:
        return {
            "success": False,
            "error": "No executed action on this incident to derive steps from",
        }
    action = executed[-1]
    incident_type = incident.get("incident_type") or classify_incident_type(
        incident.get("description") or incident.get("title") or ""
    )
    service_name = incident.get("service_name")
    params = action.get("parameters") or {}
    if isinstance(params, str):
        params = json.loads(params or "{}")
    steps = [
        {
            "order": 1,
            "action_type": action.get("action_type"),
            "parameters": params,
            "description": action.get("description"),
            "expected_outcome": "Service healthy after remediation",
        }
    ]
    sig = incident_signature(
        incident_type,
        service_name,
        action.get("action_type") or "restart_container",
    )
    row = await store.insert_runbook_draft(
        incident_type=incident_type,
        service_name=service_name,
        steps=steps,
        source_incident_id=incident_id,
        incident_signature=sig,
    )
    return {"success": True, "error": None, "runbook": row}


async def maybe_create_draft_runbook(
    incident_id: str | None,
    action: ProposedAction,
) -> None:
    """After successful resolution, optionally persist a draft runbook."""
    if not incident_id:
        return
    cfg = _runbooks_config()
    if not cfg.auto_generate_on_resolve:
        return
    if action.action_type not in cfg.allowed_auto_action_types:
        return
    incident = await store.get_incident(incident_id)
    if not incident:
        return
    incident_type = incident.get("incident_type") or classify_incident_type(
        incident.get("description") or ""
    )
    service_name = incident.get("service_name") or action.parameters.get(
        "service_name"
    )
    existing = await store.get_runbook(
        service_name or "",
        incident_type,
        status=None,
    )
    if existing and existing.get("status") in ("draft", "approved"):
        return
    steps = [
        {
            "order": 1,
            "action_type": action.action_type,
            "parameters": dict(action.parameters),
            "description": action.description,
            "expected_outcome": "Health check passed after remediation",
        }
    ]
    sig = incident_signature(incident_type, service_name, action.action_type)
    await store.insert_runbook_draft(
        incident_type=incident_type,
        service_name=service_name,
        steps=steps,
        source_incident_id=incident_id,
        incident_signature=sig,
    )
    logger.info(
        "Draft runbook created for %s / %s from incident %s",
        service_name,
        incident_type,
        incident_id,
    )


async def try_runbook_action(
    *,
    incident_id: str,
    server_id: str,
    service_name: str,
    incident_type: str,
    protected: list[str],
    auto_tier: str,
    stale_after_hours: int,
    apply_risk_override,
    maybe_auto_execute_fn,
    broadcast_pending_fn,
) -> str | None:
    """
    If an approved runbook matches, propose (and maybe auto-execute) without Claude.
    Returns 'executed', 'pending', or None.
    """
    rb = await store.get_runbook(service_name, incident_type, status="approved")
    if not rb:
        return None

    proposal = steps_to_proposed_action(
        rb.get("steps") or [],
        incident_id=incident_id,
        server_id=server_id,
        service_name=service_name,
    )
    if not proposal:
        return None

    action_type = proposal["action_type"]
    if service_name in protected:
        logger.warning("Runbook match blocked — protected service %s", service_name)
        return None
    if is_sensitive_service(server_id, service_name):
        logger.info("Runbook requires approval — sensitive service %s", service_name)
        proposal["risk_tier"] = bump_risk_for_sensitive(
            "medium", server_id, service_name
        )
    else:
        proposal["risk_tier"] = apply_risk_override(
            action_type, proposal.get("risk_tier", "low")
        )

    action_id = str(uuid.uuid4())
    action_row = await store.insert_proposed_action(
        action_id,
        incident_id=incident_id,
        action_type=action_type,
        description=proposal["description"],
        rationale=proposal["rationale"],
        risk_tier=proposal["risk_tier"],
        rollback_plan=proposal["rollback_plan"],
        parameters=proposal["parameters"],
        stale_after_hours=stale_after_hours,
    )

    await store.insert_compliance_audit(
        "action_proposed",
        server_id=server_id,
        service_name=service_name,
        incident_id=incident_id,
        action_id=action_id,
        actor="runbook",
        details={
            "risk_tier": proposal["risk_tier"],
            "action_type": action_type,
            "runbook_id": rb.get("runbook_id"),
        },
    )

    await broadcast_pending_fn(action_row)

    auto_ok = bool(rb.get("auto_executable")) and proposal["risk_tier"] == auto_tier
    if auto_ok and not is_sensitive_service(server_id, service_name):
        await maybe_auto_execute_fn(action_row, protected, auto_tier)
        return "executed"
    return "pending"
