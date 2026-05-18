"""Incident and memory MCP tools."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from db import store
from models.config import load_app_config

logger = logging.getLogger(__name__)


async def create_incident(
    server_id: str,
    title: str,
    description: str,
    severity: str,
    service_name: str | None = None,
) -> dict[str, Any]:
    try:
        incident_id = str(uuid.uuid4())
        row = await store.create_incident(
            incident_id,
            server_id,
            title,
            description,
            severity,
            service_name=service_name,
        )
        return {
            "success": True,
            "error": None,
            "incident_id": incident_id,
            "created_at": row.get("created_at"),
            "incident": row,
        }
    except Exception as exc:
        logger.warning("create_incident failed: %s", exc)
        return {"success": False, "error": str(exc)}


async def correlate_incident(
    server_id: str,
    service_name: str,
    minutes_back: int = 30,
) -> dict[str, Any]:
    try:
        cfg = load_app_config()
        window = cfg.rules.automation.correlation_window_minutes
        if minutes_back <= 0:
            minutes_back = window

        snapshots = await store.get_recent_snapshots(server_id, limit=20)
        timeline = []
        for snap in snapshots:
            timeline.append(
                {
                    "captured_at": snap.get("captured_at"),
                    "cpu_percent": snap.get("cpu_percent"),
                    "memory_percent": snap.get("memory_percent"),
                    "disk_percent": snap.get("disk_percent"),
                    "containers": snap.get("container_statuses") or [],
                }
            )

        rules = await store.list_feedback_rules(
            server_id=server_id, service_name=service_name
        )
        similar = await store.find_similar_incidents(server_id, service_name, limit=5)

        likely_cause = "Unknown — correlate without GitHub in Phase 2"
        if timeline:
            latest = timeline[0]
            containers = latest.get("containers") or []
            unhealthy = [
                c
                for c in containers
                if "exited" in (c.get("status") or "").lower()
                or "restarting" in (c.get("status") or "").lower()
            ]
            if unhealthy:
                names = ", ".join(c.get("name", "?") for c in unhealthy[:3])
                likely_cause = f"Unhealthy containers detected: {names}"

        return {
            "success": True,
            "error": None,
            "timeline": timeline,
            "likely_cause": likely_cause,
            "related_deploy": None,
            "similar_incidents": similar,
            "rules_to_respect": [r["rule"] for r in rules],
            "minutes_back": minutes_back,
        }
    except Exception as exc:
        logger.warning("correlate_incident failed: %s", exc)
        return {"success": False, "error": str(exc)}


async def store_feedback_rule(
    action_type: str,
    rule: str,
    service_name: str | None = None,
    server_id: str | None = None,
    created_from_action_id: str | None = None,
) -> dict[str, Any]:
    try:
        rule_id = await store.insert_feedback_rule(
            action_type,
            rule,
            service_name=service_name,
            server_id=server_id,
            created_from_action_id=created_from_action_id,
        )
        return {"success": True, "error": None, "rule_id": rule_id}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def draft_postmortem(incident_id: str) -> dict:
    return {"success": False, "error": "Not implemented until Phase 4"}


async def get_oncall_handoff() -> dict:
    return {"success": False, "error": "Not implemented until Phase 4"}


async def get_runbook(service_name: str, incident_type: str) -> dict:
    return {"success": False, "error": "Not implemented until Phase 4"}


async def list_pending_approvals() -> dict[str, Any]:
    try:
        pending = await store.list_pending_actions()
        return {
            "success": True,
            "error": None,
            "actions": [
                {
                    "id": a["id"],
                    "action_type": a["action_type"],
                    "description": a["description"],
                    "risk_tier": a["risk_tier"],
                    "parameters": a.get("parameters") or {},
                    "created_at": a.get("created_at"),
                }
                for a in pending
            ],
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def approve_action(action_id: str, confirm_text: str | None = None) -> dict[str, Any]:
    from approvals import approve_action_by_id

    try:
        return await approve_action_by_id(
            action_id, source="mcp", confirm_text=confirm_text
        )
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def reject_action(action_id: str, feedback: str) -> dict[str, Any]:
    from approvals import reject_action_by_id

    try:
        return await reject_action_by_id(action_id, feedback)
    except Exception as exc:
        return {"success": False, "error": str(exc)}
