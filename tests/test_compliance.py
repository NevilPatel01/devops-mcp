"""Phase 6 compliance tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agent import _maybe_auto_execute
from approvals import _serialize_action, approve_action_by_id
from compliance import bump_risk_for_sensitive, incident_compliance_fields
from db import store
from models.config import (
    ComplianceFileConfig,
    ServerConfig,
    ServersFile,
    ServiceConfig,
    ThresholdConfig,
)
from tools import executor as exec_tools
from tools import incident as incident_tools


def _sensitive_server() -> ServerConfig:
    return ServerConfig(
        id="s1",
        label="S",
        host="1.2.3.4",
        services=[
            ServiceConfig(
                name="primary DB",
                compose_file="/db/compose.yml",
                sensitive=True,
                compliance_profile="hipaa",
            )
        ],
        thresholds=ThresholdConfig(),
    )


@pytest.mark.asyncio
async def test_incident_compliance_fields_sensitive() -> None:
    with patch("compliance.load_servers_config") as mock_cfg:
        mock_cfg.return_value = ServersFile(
            compliance=ComplianceFileConfig(default_profile="none"),
            servers=[_sensitive_server()],
        )
        fields = incident_compliance_fields("s1", "primary DB")
    assert fields["is_sensitive"] == 1
    assert fields["compliance_profile"] == "hipaa"


@pytest.mark.asyncio
async def test_create_incident_sets_is_sensitive(tmp_path) -> None:
    await store.init_db(tmp_path / "c.db")
    with patch("tools.incident.incident_compliance_fields") as mock_fields:
        mock_fields.return_value = {
            "is_sensitive": 1,
            "compliance_profile": "hipaa",
        }
        result = await incident_tools.create_incident(
            "s1", "t", "d", "high", service_name="primary DB"
        )
    assert result["success"] is True
    row = await store.get_incident(result["incident_id"])
    assert row is not None
    assert row["is_sensitive"] == 1
    assert row["compliance_profile"] == "hipaa"
    audit = await store.list_compliance_audit(incident_id=result["incident_id"])
    assert any(e["event_type"] == "incident_created" for e in audit)
    await store.close_db()


@pytest.mark.asyncio
async def test_bump_risk_low_to_medium_on_sensitive() -> None:
    with patch("compliance.load_servers_config") as mock_cfg:
        mock_cfg.return_value = ServersFile(servers=[_sensitive_server()])
        assert bump_risk_for_sensitive("low", "s1", "primary DB") == "medium"
        assert bump_risk_for_sensitive("high", "s1", "primary DB") == "high"


@pytest.mark.asyncio
async def test_sensitive_blocked_without_approval() -> None:
    server = _sensitive_server()
    with patch("tools.executor._get_server", return_value=server):
        with patch("tools.executor.load_servers_config") as mock_cfg:
            mock_cfg.return_value = ServersFile(protected_services=[])
            result = await exec_tools.restart_container(
                "s1",
                "primary-db-1",
                "act-sens-1",
                approved=False,
                service_name="primary DB",
            )
    assert result["success"] is False
    assert "approval" in result["error"].lower()


@pytest.mark.asyncio
async def test_sensitive_allowed_when_approved() -> None:
    server = ServerConfig(
        id="s1",
        label="S",
        host="1.2.3.4",
        services=[
            ServiceConfig(name="api", compose_file="/x", sensitive=True),
        ],
        thresholds=ThresholdConfig(),
    )
    with patch("tools.executor._get_server", return_value=server):
        with patch("tools.executor.load_servers_config") as mock_cfg:
            mock_cfg.return_value = ServersFile(protected_services=[])
            with patch(
                "tools.executor._container_state",
                new_callable=AsyncMock,
            ) as mock_state:
                mock_state.side_effect = [{"status": "Exited"}, {"status": "Up"}]
                with patch("tools.executor.run_ssh", new_callable=AsyncMock) as mock_ssh:
                    mock_ssh.return_value = (0, "ok\n", "")
                    with patch("tools.executor.ws_broadcast", new_callable=AsyncMock):
                        result = await exec_tools.restart_container(
                            "s1",
                            "api-1",
                            "act-sens-2",
                            approved=True,
                            service_name="api",
                        )
    assert result["success"] is True


@pytest.mark.asyncio
async def test_protected_still_blocked() -> None:
    server = _sensitive_server()
    with patch("tools.executor._get_server", return_value=server):
        with patch("tools.executor.load_servers_config") as mock_cfg:
            mock_cfg.return_value = ServersFile(protected_services=["primary DB"])
            result = await exec_tools.restart_container(
                "s1",
                "primary-db-1",
                "act-prot",
                approved=True,
                service_name="primary DB",
            )
    assert result["success"] is False
    assert "protected" in result["error"].lower()


@pytest.mark.asyncio
async def test_auto_exec_skips_sensitive(tmp_path) -> None:
    await store.init_db(tmp_path / "auto.db")
    action_row = {
        "id": "a1",
        "risk_tier": "low",
        "parameters": {"server_id": "s1", "service_name": "primary DB"},
        "action_type": "restart_container",
        "description": "restart",
        "rationale": "test",
        "rollback_plan": "manual",
    }
    with patch("agent.is_sensitive_service", return_value=True):
        with patch("agent.execute_and_finalize", new_callable=AsyncMock) as mock_exec:
            await _maybe_auto_execute(action_row, [], "low")
            mock_exec.assert_not_called()
    await store.close_db()


@pytest.mark.asyncio
async def test_serialize_action_compliance_fields() -> None:
    row = {
        "id": "x",
        "action_type": "restart_container",
        "description": "d",
        "rationale": "r",
        "risk_tier": "high",
        "rollback_plan": "b",
        "parameters": {"server_id": "s1", "service_name": "primary DB"},
        "status": "pending",
    }
    with patch("approvals.service_compliance_meta") as mock_meta:
        mock_meta.return_value = {
            "sensitive": True,
            "compliance_profile": "hipaa",
        }
        payload = _serialize_action(row)
    assert payload["compliance_sensitive"] is True
    assert payload["compliance_profile"] == "hipaa"
    assert payload["requires_compliance_ack"] is True


@pytest.mark.asyncio
async def test_sensitive_high_requires_compliance_ack(tmp_path) -> None:
    await store.init_db(tmp_path / "ack.db")
    action_id = "act-ch"
    await store.insert_proposed_action(
        action_id,
        incident_id=None,
        action_type="run_ssh_command",
        description="x",
        rationale="y",
        risk_tier="high",
        rollback_plan="z",
        parameters={"server_id": "s1", "service_name": "primary DB"},
    )
    with patch("approvals.service_compliance_meta") as mock_meta:
        mock_meta.return_value = {"sensitive": True, "compliance_profile": "hipaa"}
        bad = await approve_action_by_id(
            action_id,
            source="dashboard",
            confirm_text="CONFIRM",
            compliance_confirm_text="WRONG",
        )
        assert bad["success"] is False
        assert "COMPLIANCE" in bad["error"]
    await store.close_db()


@pytest.mark.asyncio
async def test_mcp_compliance_tools() -> None:
    from tools import compliance as compliance_tools

    with patch("tools.compliance.service_compliance_meta") as mock_meta:
        mock_meta.return_value = {
            "sensitive": True,
            "compliance_profile": "hipaa",
            "policy_hints": ["hint"],
        }
        with patch(
            "tools.compliance.store.list_compliance_audit",
            new_callable=AsyncMock,
            return_value=[],
        ):
            ctx = await compliance_tools.get_compliance_context("s1", "primary DB")
    assert ctx["success"] is True
    assert ctx["sensitive"] is True
