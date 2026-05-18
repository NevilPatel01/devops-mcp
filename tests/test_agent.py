"""Agent and approval gate tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from approvals import approve_action_by_id
from db import store
from models.incident import AnomalyEvent


@pytest.mark.asyncio
async def test_mcp_rejects_high_risk_approval(tmp_path) -> None:
    db_file = tmp_path / "agent.db"
    await store.init_db(db_file)
    action_id = "act-high-1"
    await store.insert_proposed_action(
        action_id,
        incident_id=None,
        action_type="run_ssh_command",
        description="Dangerous",
        rationale="test",
        risk_tier="high",
        rollback_plan="none",
        parameters={"server_id": "fct-droplet"},
    )
    result = await approve_action_by_id(action_id, source="mcp")
    assert result["success"] is False
    assert "HIGH" in result["error"]
    await store.close_db()


@pytest.mark.asyncio
async def test_agent_skips_when_pending_exists(tmp_path) -> None:
    db_file = tmp_path / "agent2.db"
    await store.init_db(db_file)
    await store.insert_proposed_action(
        "pending-1",
        incident_id=None,
        action_type="restart_container",
        description="x",
        rationale="y",
        risk_tier="low",
        rollback_plan="z",
        parameters={"server_id": "fct-droplet", "container_name": "test-nginx"},
    )
    with patch("agent._call_claude", new_callable=AsyncMock) as mock_claude:
        from agent import run_agent_loop

        await run_agent_loop(
            AnomalyEvent(
                server_id="fct-droplet",
                service_name="test-nginx",
                reason="test",
            )
        )
        mock_claude.assert_not_called()
    await store.close_db()


@pytest.mark.asyncio
async def test_correlate_without_github() -> None:
    from tools import incident as incident_tools

    with patch("tools.incident.load_app_config") as mock_cfg:
        from models.config import AppConfig, AutomationConfig, RulesFile, ServersFile

        mock_cfg.return_value = AppConfig(
            servers=ServersFile(),
            rules=RulesFile(automation=AutomationConfig(correlation_window_minutes=30)),
        )
        with patch(
            "tools.incident.store.get_recent_snapshots", new_callable=AsyncMock
        ) as mock_snaps:
            mock_snaps.return_value = []
            with patch(
                "tools.incident.store.list_feedback_rules", new_callable=AsyncMock
            ) as mock_rules:
                mock_rules.return_value = []
                with patch(
                    "tools.incident.store.find_similar_incidents",
                    new_callable=AsyncMock,
                ) as mock_sim:
                    mock_sim.return_value = []
                    result = await incident_tools.correlate_incident(
                        "fct-droplet", "test-nginx"
                    )
    assert result["success"] is True
    assert result["related_deploy"] is None
