"""False-positive learning: fatigue scores, suppressions, baseline refresh."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from anomaly_detection import anomaly_signature
from db import store
from models.config import FalsePositiveConfig, load_rules_config

logger = logging.getLogger(__name__)


async def process_false_positive(
    incident_id: str,
    *,
    reason: str | None = None,
    suppress_similar_hours: int | None = None,
    actor: str = "dashboard",
) -> dict[str, Any]:
    """Mark incident false positive and apply learning side effects."""
    incident = await store.get_incident(incident_id)
    if not incident:
        return {"success": False, "error": "Incident not found"}

    try:
        fp_cfg = load_rules_config().false_positive
    except (FileNotFoundError, OSError):
        fp_cfg = FalsePositiveConfig()
    hours = (
        suppress_similar_hours
        if suppress_similar_hours is not None
        else fp_cfg.default_suppression_hours
    )
    hours = max(0, min(hours, 168))

    row = await store.mark_incident_false_positive(incident_id)
    if not row:
        return {"success": False, "error": "Failed to update incident"}

    server_id = row.get("server_id") or ""
    service_name = row.get("service_name")
    anomaly_reason = reason or row.get("description") or row.get("title") or ""

    await store.increment_alert_fatigue(
        server_id,
        service_name or "",
        false_positive=True,
    )

    suppression_id: int | None = None
    if hours > 0 and anomaly_reason:
        signature = anomaly_signature(anomaly_reason, service_name)
        expires_at = (
            datetime.now(UTC).replace(microsecond=0) + timedelta(hours=hours)
        ).isoformat()
        suppression_id = await store.insert_suppression_pattern(
            server_id=server_id,
            service_name=service_name,
            pattern_type="anomaly_signature",
            pattern_json={"signature": signature, "reason": anomaly_reason[:500]},
            created_from_incident_id=incident_id,
            expires_at=expires_at,
        )
        logger.info(
            "Suppression %s for %s until %s",
            suppression_id,
            signature,
            expires_at,
        )

    if server_id:
        cpu_p95, mem_p95 = await store.compute_baseline_p95(server_id, hours=24)
        await store.upsert_baseline(server_id, cpu_p95, mem_p95)
        if service_name:
            await store.upsert_service_baseline(
                server_id,
                service_name,
                cpu_p95=cpu_p95,
                memory_p95=mem_p95,
            )

    fatigue = await store.get_alert_fatigue(server_id, service_name or "")
    return {
        "success": True,
        "error": None,
        "incident": row,
        "suppression_id": suppression_id,
        "fatigue_score": fatigue.get("fatigue_score") if fatigue else None,
    }
