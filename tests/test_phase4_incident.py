"""Phase 4 incident tools tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from db import store
from tools import incident as incident_tools


@pytest.mark.asyncio
async def test_get_runbook_not_found() -> None:
    result = await incident_tools.get_runbook("unknown", "crash")
    assert result["success"] is True
    assert result["found"] is False


@pytest.mark.asyncio
async def test_draft_postmortem_fallback(tmp_path) -> None:
    await store.init_db(tmp_path / "pm.db")
    inc_id = "inc-pm-1"
    await store.create_incident(inc_id, "s1", "t", "d", "high")
    with patch("tools.incident._claude_markdown", new_callable=AsyncMock) as mock_claude:
        mock_claude.return_value = "# Postmortem\n\nDone."
        with patch(
            "tools.incident.correlate_incident", new_callable=AsyncMock
        ) as mock_corr:
            mock_corr.return_value = {"success": True, "timeline": []}
            result = await incident_tools.draft_postmortem(inc_id)
    assert result["success"] is True
    assert "Postmortem" in result["postmortem_markdown"]
    row = await store.get_incident(inc_id)
    assert row.get("postmortem_draft")
    await store.close_db()


@pytest.mark.asyncio
async def test_rollback_deployment_no_image() -> None:
    from models.config import ServerConfig, ThresholdConfig
    from tools import executor as exec_tools

    server = ServerConfig(id="s1", label="S", host="1.2.3.4", thresholds=ThresholdConfig())
    with patch("tools.executor._get_server", return_value=server):
        with patch("tools.executor.load_servers_config") as mock_cfg:
            mock_cfg.return_value = type("X", (), {"protected_services": []})()
            with patch(
                "db.store.get_last_healthy_image", new_callable=AsyncMock, return_value=None
            ):
                with patch(
                    "db.store.get_latest_snapshot", new_callable=AsyncMock, return_value=None
                ):
                    result = await exec_tools.rollback_deployment(
                        "s1", "web", "/opt/c.yml", "a1", approved=True
                    )
    assert result["success"] is False
    assert "healthy snapshot" in result["error"].lower()
