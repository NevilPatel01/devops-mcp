"""Claude reasoning loop — implemented in Phase 2."""

from __future__ import annotations

import logging

from models.incident import AnomalyEvent

logger = logging.getLogger(__name__)


async def run_agent_loop(anomaly: AnomalyEvent) -> None:
    """Observe → analyse → plan → gate → execute → verify (Phase 2+)."""
    logger.info("Agent stub: anomaly on %s — %s", anomaly.server_id, anomaly.reason)
