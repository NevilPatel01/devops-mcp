"""Shared approve/reject logic for WebSocket and MCP."""

from __future__ import annotations

import logging
from typing import Any

from db import store
from executor import execute_and_finalize
from models.incident import ProposedAction
from tools import incident as incident_tools
from ws_hub import ws_broadcast

logger = logging.getLogger(__name__)


def _action_from_row(row: dict[str, Any]) -> ProposedAction:
    return ProposedAction(
        id=row["id"],
        incident_id=row.get("incident_id"),
        action_type=row["action_type"],
        description=row["description"],
        rationale=row["rationale"],
        risk_tier=row["risk_tier"],
        rollback_plan=row["rollback_plan"],
        parameters=row.get("parameters") or {},
        status=row.get("status", "pending"),
    )


def _serialize_action(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "incident_id": row.get("incident_id"),
        "action_type": row["action_type"],
        "description": row["description"],
        "rationale": row["rationale"],
        "risk_tier": row["risk_tier"],
        "rollback_plan": row["rollback_plan"],
        "parameters": row.get("parameters") or {},
        "status": row.get("status"),
        "created_at": row.get("created_at"),
    }


async def approve_action_by_id(
    action_id: str,
    *,
    source: str = "dashboard",
    confirm_text: str | None = None,
) -> dict[str, Any]:
    row = await store.get_proposed_action(action_id)
    if not row:
        return {"success": False, "error": f"Unknown action_id: {action_id}"}
    if row.get("status") != "pending":
        return {
            "success": False,
            "error": f"Action {action_id} is not pending (status={row.get('status')})",
        }

    risk = (row.get("risk_tier") or "").lower()
    if risk == "high":
        if source == "mcp":
            return {
                "success": False,
                "error": "HIGH risk actions require dashboard approval with CONFIRM",
            }
        if (confirm_text or "").strip().upper() != "CONFIRM":
            return {
                "success": False,
                "error": 'Type CONFIRM to approve HIGH risk actions',
            }

    await store.update_action_status(action_id, "approved")
    action = _action_from_row(row)
    result = await execute_and_finalize(action)

    return {
        "success": bool(result.get("success")) and result.get("health_ok", True),
        "error": result.get("error") or (
            None if result.get("health_ok", True) else result.get("health_message")
        ),
        "action_id": action_id,
        "output": result.get("output"),
        "health_ok": result.get("health_ok"),
    }


async def reject_action_by_id(action_id: str, feedback: str) -> dict[str, Any]:
    row = await store.get_proposed_action(action_id)
    if not row:
        return {"success": False, "error": f"Unknown action_id: {action_id}"}
    if row.get("status") != "pending":
        return {
            "success": False,
            "error": f"Action {action_id} is not pending (status={row.get('status')})",
        }

    await store.update_action_status(
        action_id, "rejected", reviewer_feedback=feedback or None
    )
    params = row.get("parameters") or {}
    if feedback.strip():
        await incident_tools.store_feedback_rule(
            row["action_type"],
            feedback.strip(),
            service_name=params.get("service_name"),
            server_id=params.get("server_id"),
            created_from_action_id=action_id,
        )

    if row.get("incident_id"):
        await store.update_incident_status(row["incident_id"], "dismissed")

    await ws_broadcast(
        {
            "type": "action_rejected",
            "action_id": action_id,
            "feedback": feedback,
        }
    )
    return {"success": True, "error": None, "action_id": action_id}


async def broadcast_pending_actions() -> None:
    for row in await store.list_pending_actions():
        await ws_broadcast(
            {"type": "action_pending", "action": _serialize_action(row)}
        )
