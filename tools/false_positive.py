"""False-positive learning MCP tools."""

from __future__ import annotations

import logging
from typing import Any

from db import store
from false_positive_handler import process_false_positive

logger = logging.getLogger(__name__)


async def mark_false_positive(
    incident_id: str,
    reason: str | None = None,
    suppress_similar_hours: int | None = None,
) -> dict[str, Any]:
    try:
        return await process_false_positive(
            incident_id,
            reason=reason,
            suppress_similar_hours=suppress_similar_hours,
            actor="mcp",
        )
    except Exception as exc:
        logger.warning("mark_false_positive failed: %s", exc)
        return {"success": False, "error": str(exc)}


async def list_suppression_patterns(server_id: str | None = None) -> dict[str, Any]:
    try:
        patterns = await store.list_suppression_patterns(server_id, active_only=True)
        return {"success": True, "error": None, "patterns": patterns}
    except Exception as exc:
        return {"success": False, "error": str(exc), "patterns": []}


async def clear_suppression_pattern(pattern_id: int) -> dict[str, Any]:
    try:
        ok = await store.delete_suppression_pattern(int(pattern_id))
        if not ok:
            return {"success": False, "error": "Pattern not found"}
        return {"success": True, "error": None}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
