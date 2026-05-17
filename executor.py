"""Risk-gated execution orchestration — implemented in Phase 3."""

from __future__ import annotations

import logging

from models.incident import ProposedAction

logger = logging.getLogger(__name__)


async def execute(action: ProposedAction, *, approved: bool = False) -> dict:
    """Execute a proposed action after approval checks (Phase 3)."""
    logger.info("Executor stub: %s (approved=%s)", action.action_type, approved)
    return {
        "success": False,
        "error": "Executor not implemented until Phase 3",
    }
