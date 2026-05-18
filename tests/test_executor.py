"""Executor and execution tool tests — mock SSH, no real VPS."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from executor import execute_and_finalize
from models.config import ServerConfig, ServersFile, ServiceConfig, ThresholdConfig
from models.incident import ProposedAction
from tools import executor as exec_tools


@pytest.mark.asyncio
async def test_restart_blocked_without_approval() -> None:
    with patch("tools.executor._get_server") as mock_srv:
        mock_srv.return_value = ServerConfig(
            id="s1", label="S", host="1.2.3.4", thresholds=ThresholdConfig()
        )
        result = await exec_tools.restart_container(
            "s1", "web", "act-1", approved=False
        )
    assert result["success"] is False
    assert "approval" in result["error"].lower()


@pytest.mark.asyncio
async def test_restart_blocked_for_protected_service() -> None:
    server = ServerConfig(
        id="s1",
        label="S",
        host="1.2.3.4",
        services=[ServiceConfig(name="primary DB", compose_file="/x", sensitive=True)],
        thresholds=ThresholdConfig(),
    )
    with patch("tools.executor._get_server", return_value=server):
        with patch("tools.executor.load_servers_config") as mock_cfg:
            mock_cfg.return_value = ServersFile(protected_services=["primary DB"])
            result = await exec_tools.restart_container(
                "s1",
                "primary-db-1",
                "act-2",
                approved=True,
                service_name="primary DB",
            )
    assert result["success"] is False
    assert "protected" in result["error"].lower()


@pytest.mark.asyncio
async def test_restart_success_mock_ssh() -> None:
    server = ServerConfig(id="s1", label="S", host="1.2.3.4", thresholds=ThresholdConfig())
    with patch("tools.executor._get_server", return_value=server):
        with patch("tools.executor.load_servers_config") as mock_cfg:
            mock_cfg.return_value = ServersFile(protected_services=[])
            with patch(
                "tools.executor._container_state",
                new_callable=AsyncMock,
            ) as mock_state:
                mock_state.side_effect = [
                    {"status": "Exited"},
                    {"status": "Up 2 seconds"},
                ]
                with patch("tools.executor.run_ssh", new_callable=AsyncMock) as mock_ssh:
                    mock_ssh.return_value = (0, "web\n", "")
                    with patch("tools.executor.ws_broadcast", new_callable=AsyncMock):
                        result = await exec_tools.restart_container(
                            "s1", "web", "act-3", approved=True
                        )
    assert result["success"] is True


@pytest.mark.asyncio
async def test_execute_and_finalize_health_failure_opens_incident(tmp_path) -> None:
    from db import store

    db_file = tmp_path / "exec.db"
    await store.init_db(db_file)

    action = ProposedAction(
        id="act-hc-1",
        incident_id="inc-1",
        action_type="restart_container",
        description="restart",
        rationale="test",
        risk_tier="low",
        rollback_plan="stop",
        parameters={
            "server_id": "s1",
            "container_name": "web",
            "service_name": "test-nginx",
        },
    )
    await store.insert_proposed_action(
        action.id,
        incident_id=action.incident_id,
        action_type=action.action_type,
        description=action.description,
        rationale=action.rationale,
        risk_tier=action.risk_tier,
        rollback_plan=action.rollback_plan,
        parameters=action.parameters,
    )

    with patch("executor.execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = {"success": True, "output": "ok"}
        with patch(
            "executor._post_action_health_check", new_callable=AsyncMock
        ) as mock_hc:
            mock_hc.return_value = (False, "still exited")
            with patch(
                "executor._create_health_failure_incident", new_callable=AsyncMock
            ) as mock_inc:
                mock_inc.return_value = "inc-followup"
                with patch("executor.ws_broadcast", new_callable=AsyncMock):
                    result = await execute_and_finalize(action)

    assert result["success"] is True
    assert result["health_ok"] is False
    mock_inc.assert_called_once()
    await store.close_db()


@pytest.mark.asyncio
async def test_run_compose_command_mock() -> None:
    server = ServerConfig(id="s1", label="S", host="1.2.3.4", thresholds=ThresholdConfig())
    with patch("tools.executor._get_server", return_value=server):
        with patch("tools.executor.load_servers_config") as mock_cfg:
            mock_cfg.return_value = ServersFile()
            with patch(
                "tools.executor.detect_compose_command",
                new_callable=AsyncMock,
                return_value="docker compose",
            ):
                with patch("tools.executor.run_ssh", new_callable=AsyncMock) as mock_ssh:
                    mock_ssh.return_value = (0, "done\n", "")
                    with patch("tools.executor.ws_broadcast", new_callable=AsyncMock):
                        result = await exec_tools.run_compose_command(
                            "s1",
                            "/opt/app/docker-compose.yml",
                            "restart api",
                            "act-c",
                            approved=True,
                        )
    assert result["success"] is True
