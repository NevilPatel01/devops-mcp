"""Compliance MCP tools (Phase 6)."""

from __future__ import annotations

import logging
from typing import Any

from compliance import service_compliance_meta
from db import store

logger = logging.getLogger(__name__)


async def get_compliance_context(
    server_id: str,
    service_name: str,
) -> dict[str, Any]:
    try:
        meta = service_compliance_meta(server_id, service_name)
        audit_recent = await store.list_compliance_audit(
            hours=24,
            limit=20,
        )
        scoped = [
            row
            for row in audit_recent
            if row.get("server_id") == server_id
            and (not service_name or row.get("service_name") == service_name)
        ]
        return {
            "success": True,
            "error": None,
            "sensitive": meta["sensitive"],
            "compliance_profile": meta["compliance_profile"],
            "policy_hints": meta["policy_hints"],
            "audit_recent": scoped[:10],
        }
    except Exception as exc:
        logger.warning("get_compliance_context failed: %s", exc)
        return {"success": False, "error": str(exc)}


async def list_compliance_audit(
    incident_id: str | None = None,
    hours: int = 24,
) -> dict[str, Any]:
    try:
        rows = await store.list_compliance_audit(
            incident_id=incident_id,
            hours=max(1, min(hours, 168)),
        )
        return {"success": True, "error": None, "entries": rows}
    except Exception as exc:
        logger.warning("list_compliance_audit failed: %s", exc)
        return {"success": False, "error": str(exc)}
