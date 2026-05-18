"""Claude reasoning loop — one-shot JSON, no API tool loop."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from typing import Any

from anthropic import AsyncAnthropic

from approvals import _serialize_action
from compliance import (
    bump_risk_for_sensitive,
    is_sensitive_service,
    service_compliance_meta,
)
from db import store
from executor import execute_and_finalize
from models.config import load_app_config
from models.incident import AnomalyEvent, ProposedAction
from tools import incident as incident_tools
from ws_hub import ws_broadcast

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-5"
_server_locks: dict[str, asyncio.Lock] = {}
_reminder_tasks: dict[str, asyncio.Task] = {}

SYSTEM_PROMPT = """You are an autonomous DevOps AI agent monitoring real infrastructure.
Analyse the anomaly and context, then propose ONE specific remediation.

Rules:
1. Output ONLY valid JSON (no markdown fences, no prose).
2. Fields: action_type, description, rationale, risk_tier, rollback_plan, parameters
3. action_type: restart_container | run_compose_command | scale_service |
   run_ssh_command | rollback_deployment (requires compose_file + service_name).
4. parameters must include: server_id, container_name, service_name (if known)
5. risk_tier: low | medium | high
   - low: restart single non-sensitive container only
   - medium: compose changes, rollbacks
   - high: arbitrary SSH, data operations
6. NEVER propose actions on protected_services. For sensitive_services use medium+ risk
   and include a compliance impact sentence in rationale.
7. Respect all feedback rules in context.

Example keys: action_type, description, rationale, risk_tier, rollback_plan, parameters.
"""


def _lock_for(server_id: str) -> asyncio.Lock:
    if server_id not in _server_locks:
        _server_locks[server_id] = asyncio.Lock()
    return _server_locks[server_id]


def _parse_proposal(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                return None
    return None


def _apply_risk_overrides(action_type: str, risk_tier: str) -> str:
    try:
        cfg = load_app_config()
        for override in cfg.rules.risk_overrides:
            if override.action_type == action_type:
                return override.risk_tier
    except FileNotFoundError:
        pass
    return risk_tier


def _is_protected(service_name: str | None, protected: list[str]) -> bool:
    if not service_name:
        return False
    return service_name in protected


async def _call_claude(user_message: str) -> dict[str, Any] | None:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key or api_key.startswith("sk-ant-..."):
        logger.error("ANTHROPIC_API_KEY not configured in .env")
        return None
    client = AsyncAnthropic(api_key=api_key)
    response = await client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    parts = [b.text for b in response.content if hasattr(b, "text")]
    return _parse_proposal("".join(parts))


async def _schedule_reminder(action_id: str, delay: int) -> None:
    existing = _reminder_tasks.pop(action_id, None)
    if existing and not existing.done():
        existing.cancel()

    async def _remind() -> None:
        try:
            await asyncio.sleep(delay)
            row = await store.get_proposed_action(action_id)
            if not row or row.get("status") != "pending":
                return
            await ws_broadcast(
                {
                    "type": "action_pending_reminder",
                    "action_id": action_id,
                    "action": _serialize_action(row),
                    "message": (
                        "Action still pending — approve in dashboard or use MCP "
                        "list_pending_approvals / approve_action (not for HIGH risk)."
                    ),
                }
            )
        except asyncio.CancelledError:
            pass

    _reminder_tasks[action_id] = asyncio.create_task(_remind())


async def _maybe_auto_execute(
    action_row: dict[str, Any],
    protected: list[str],
    auto_tier: str,
) -> None:
    risk = (action_row.get("risk_tier") or "").lower()
    params = action_row.get("parameters") or {}
    service_name = params.get("service_name")
    server_id = params.get("server_id")
    if _is_protected(service_name, protected):
        logger.info("Skipping auto-exec: protected service %s", service_name)
        return
    if is_sensitive_service(server_id, service_name):
        logger.info("Skipping auto-exec: sensitive service %s", service_name)
        return
    if risk != auto_tier:
        return

    action = ProposedAction(
        id=action_row["id"],
        incident_id=action_row.get("incident_id"),
        action_type=action_row["action_type"],
        description=action_row["description"],
        rationale=action_row["rationale"],
        risk_tier=action_row["risk_tier"],
        rollback_plan=action_row["rollback_plan"],
        parameters=params,
    )
    await store.update_action_status(action_row["id"], "approved")
    await execute_and_finalize(action)


async def run_agent_loop(anomaly: AnomalyEvent) -> None:
    """Observe → analyse → plan → gate (execute in Phase 2 for LOW auto only)."""
    lock = _lock_for(anomaly.server_id)
    if lock.locked():
        logger.debug("Agent already running for %s", anomaly.server_id)
        return

    async with lock:
        pending = await store.get_pending_action_for_server(anomaly.server_id)
        if pending:
            logger.info(
                "Skipping agent for %s — pending action %s",
                anomaly.server_id,
                pending["id"],
            )
            return

        try:
            cfg = load_app_config()
        except FileNotFoundError as exc:
            logger.warning("Agent: %s", exc)
            return

        protected = cfg.servers.protected_services
        service_name = anomaly.service_name or "unknown"
        if _is_protected(service_name, protected):
            logger.warning(
                "Anomaly on protected service %s — no automated proposal",
                service_name,
            )
            return

        incident_id = str(uuid.uuid4())
        title = f"Anomaly on {anomaly.server_id}"
        if service_name:
            title = f"{service_name} unhealthy on {anomaly.server_id}"

        inc = await incident_tools.create_incident(
            anomaly.server_id,
            title,
            anomaly.reason,
            anomaly.severity,
            service_name=anomaly.service_name,
        )
        if not inc.get("success"):
            logger.error("Failed to create incident: %s", inc.get("error"))
            return
        incident_id = inc["incident_id"]

        await ws_broadcast(
            {
                "type": "incident_created",
                "incident": inc.get("incident") or {"id": incident_id},
            }
        )

        correlation = await incident_tools.correlate_incident(
            anomaly.server_id,
            service_name,
            minutes_back=cfg.rules.automation.correlation_window_minutes,
        )
        rules = await store.list_feedback_rules(
            server_id=anomaly.server_id,
            service_name=anomaly.service_name,
        )
        snapshots = await store.get_recent_snapshots(anomaly.server_id, limit=5)

        sensitive_services: list[dict[str, Any]] = []
        compliance_profiles: dict[str, str] = {}
        for srv in cfg.servers.servers:
            if srv.id != anomaly.server_id:
                continue
            for svc in srv.services:
                if svc.sensitive:
                    profile = svc.compliance_profile or (
                        cfg.servers.compliance.default_profile
                    )
                    sensitive_services.append(
                        {"name": svc.name, "compliance_profile": profile}
                    )
                    compliance_profiles[svc.name] = profile

        svc_meta = service_compliance_meta(
            anomaly.server_id, anomaly.service_name
        )
        user_payload = {
            "anomaly": {
                "server_id": anomaly.server_id,
                "service_name": anomaly.service_name,
                "reason": anomaly.reason,
                "severity": anomaly.severity,
                "metrics": anomaly.metrics,
            },
            "correlation": correlation,
            "feedback_rules": [r["rule"] for r in rules],
            "protected_services": protected,
            "sensitive_services": sensitive_services,
            "compliance_profiles": compliance_profiles,
            "compliance_policy_hints": svc_meta.get("policy_hints", []),
            "recent_snapshots": snapshots,
        }
        proposal = await _call_claude(json.dumps(user_payload, default=str))
        if not proposal:
            logger.error("Claude returned no valid proposal for %s", anomaly.server_id)
            return

        action_type = proposal.get("action_type", "restart_container")
        risk_tier = _apply_risk_overrides(
            action_type, (proposal.get("risk_tier") or "medium").lower()
        )
        params = proposal.get("parameters") or {}
        params.setdefault("server_id", anomaly.server_id)
        if anomaly.service_name:
            params.setdefault("service_name", anomaly.service_name)

        risk_tier = bump_risk_for_sensitive(
            risk_tier, params.get("server_id"), params.get("service_name")
        )

        if _is_protected(params.get("service_name"), protected):
            logger.warning("Claude proposed protected service — discarding")
            return

        action_id = str(uuid.uuid4())
        action_row = await store.insert_proposed_action(
            action_id,
            incident_id=incident_id,
            action_type=action_type,
            description=proposal.get("description", "Remediation"),
            rationale=proposal.get("rationale", ""),
            risk_tier=risk_tier,
            rollback_plan=proposal.get("rollback_plan", "Manual intervention"),
            parameters=params,
            stale_after_hours=cfg.rules.automation.stale_after_hours,
        )

        await store.insert_compliance_audit(
            "action_proposed",
            server_id=params.get("server_id"),
            service_name=params.get("service_name"),
            incident_id=incident_id,
            action_id=action_id,
            actor="agent",
            details={
                "risk_tier": risk_tier,
                "action_type": action_type,
                "compliance_sensitive": is_sensitive_service(
                    params.get("server_id"), params.get("service_name")
                ),
            },
        )

        serialized = _serialize_action(action_row)
        await ws_broadcast({"type": "action_pending", "action": serialized})

        auto_tier = cfg.rules.automation.auto_execute_risk_tier.lower()
        if risk_tier == auto_tier:
            await _maybe_auto_execute(action_row, protected, auto_tier)
        else:
            delay = cfg.rules.automation.approval_timeout_seconds
            await _schedule_reminder(action_id, delay)
