"""False-positive learning and suppression tests."""

import pytest

from anomaly_detection import anomaly_signature
from db import store
from false_positive_handler import process_false_positive


@pytest.mark.asyncio
async def test_false_positive_increments_fatigue(tmp_path) -> None:
    await store.init_db(tmp_path / "fp.db")
    inc = await store.create_incident(
        "i1",
        "srv1",
        "High CPU",
        "CPU spike during deploy",
        "low",
        service_name="api",
    )
    result = await process_false_positive(
        inc["id"],
        reason="deploy noise",
        suppress_similar_hours=24,
        actor="test",
    )
    assert result["success"] is True
    fatigue = await store.get_alert_fatigue("srv1", "api")
    assert fatigue is not None
    assert fatigue["false_positive_count"] == 1
    assert fatigue["fatigue_score"] > 0


@pytest.mark.asyncio
async def test_suppression_blocks_matching_signature(tmp_path) -> None:
    await store.init_db(tmp_path / "sup.db")
    reason = "CPU 90% above threshold"
    sig = anomaly_signature(reason, "api")
    await store.insert_suppression_pattern(
        server_id="srv1",
        service_name="api",
        pattern_type="anomaly_signature",
        pattern_json={"signature": sig, "reason": reason},
        expires_at="2099-01-01T00:00:00+00:00",
    )
    assert await store.is_anomaly_suppressed("srv1", sig, "api") is True
    assert await store.is_anomaly_suppressed("srv1", "other|api", "api") is False


@pytest.mark.asyncio
async def test_service_scoped_suppression_ignores_server_wide_anomaly(tmp_path) -> None:
    """Pattern for service 'api' must not suppress anomalies with service_name=None."""
    await store.init_db(tmp_path / "scoped.db")
    reason = "CPU 90% above threshold"
    await store.insert_suppression_pattern(
        server_id="srv1",
        service_name="api",
        pattern_type="anomaly_signature",
        pattern_json={"signature": anomaly_signature(reason, "api"), "reason": reason},
        expires_at="2099-01-01T00:00:00+00:00",
    )
    server_wide_sig = anomaly_signature(reason, None)
    assert await store.is_anomaly_suppressed("srv1", server_wide_sig, None) is False
    assert await store.is_anomaly_suppressed("srv1", reason, None) is False


@pytest.mark.asyncio
async def test_server_wide_suppression_matches_any_service(tmp_path) -> None:
    await store.init_db(tmp_path / "wide.db")
    reason = "Disk 95% above threshold"
    sig = anomaly_signature(reason, None)
    await store.insert_suppression_pattern(
        server_id="srv1",
        service_name=None,
        pattern_type="anomaly_signature",
        pattern_json={"signature": sig, "reason": reason},
        expires_at="2099-01-01T00:00:00+00:00",
    )
    assert await store.is_anomaly_suppressed("srv1", sig, None) is True
    # Server-wide pattern may suppress other services when reason text matches
    assert (
        await store.is_anomaly_suppressed(
            "srv1", anomaly_signature(reason, "api"), "api"
        )
        is True
    )
