"""Runbook engine and store tests."""

import pytest

from db import store
from models.incident import ProposedAction
from runbook_engine import (
    classify_incident_type,
    draft_runbook_from_incident,
    incident_signature,
    maybe_create_draft_runbook,
    steps_to_proposed_action,
)


def test_classify_container_exited() -> None:
    assert classify_incident_type("Container api exited with code 1") == "container_exited"


def test_classify_high_cpu() -> None:
    assert classify_incident_type("CPU 92% above threshold") == "high_cpu"


def test_steps_to_proposed_action() -> None:
    steps = [
        {
            "order": 1,
            "action_type": "restart_container",
            "parameters": {"container_name": "api"},
            "description": "Restart API",
        }
    ]
    proposal = steps_to_proposed_action(
        steps,
        incident_id="inc-1",
        server_id="srv1",
        service_name="api",
    )
    assert proposal is not None
    assert proposal["action_type"] == "restart_container"
    assert proposal["parameters"]["server_id"] == "srv1"
    assert proposal["parameters"]["service_name"] == "api"


@pytest.mark.asyncio
async def test_draft_and_approve_runbook(tmp_path) -> None:
    await store.init_db(tmp_path / "rb.db")
    inc = await store.create_incident(
        "inc-rb",
        "srv1",
        "api down",
        "Container exited",
        "low",
        service_name="api",
    )
    await store.update_incident_type(inc["id"], "container_exited")
    action_id = "act-1"
    await store.insert_proposed_action(
        action_id,
        incident_id=inc["id"],
        action_type="restart_container",
        description="Restart api",
        rationale="Fix crash",
        risk_tier="low",
        rollback_plan="Manual",
        parameters={"server_id": "srv1", "service_name": "api", "container_name": "api"},
    )
    await store.update_action_status(action_id, "executed")

    draft = await draft_runbook_from_incident(inc["id"])
    assert draft["success"] is True
    rb_id = draft["runbook"]["runbook_id"]
    assert draft["runbook"]["status"] == "draft"

    approved = await store.approve_runbook(rb_id, auto_executable=True, approved_by="test")
    assert approved is not None
    assert approved["status"] == "approved"
    assert approved["auto_executable"] == 1

    matched = await store.get_runbook("api", "container_exited", status="approved")
    assert matched is not None
    assert matched["runbook_id"] == rb_id


@pytest.mark.asyncio
async def test_maybe_create_draft_on_resolve(tmp_path, monkeypatch) -> None:
    await store.init_db(tmp_path / "rb2.db")
    inc = await store.create_incident(
        "inc2",
        "srv1",
        "CPU high",
        "CPU 95%",
        "low",
        service_name="api",
    )
    await store.update_incident_type(inc["id"], "high_cpu")

    action = ProposedAction(
        id="a2",
        incident_id=inc["id"],
        action_type="restart_container",
        description="Restart",
        rationale="Fix",
        risk_tier="low",
        rollback_plan="None",
        parameters={"server_id": "srv1", "service_name": "api", "container_name": "api"},
    )
    await maybe_create_draft_runbook(inc["id"], action)
    rows = await store.list_runbooks(service_name="api", status="draft")
    assert len(rows) == 1
    sig = incident_signature("high_cpu", "api", "restart_container")
    assert rows[0]["incident_signature"] == sig


@pytest.mark.asyncio
async def test_approved_runbook_not_matched_for_draft_only(tmp_path) -> None:
    await store.init_db(tmp_path / "rb3.db")
    await store.insert_runbook_draft(
        incident_type="high_cpu",
        service_name="api",
        steps=[{"order": 1, "action_type": "restart_container", "parameters": {}}],
    )
    assert await store.get_runbook("api", "high_cpu", status="approved") is None
    assert await store.get_runbook("api", "high_cpu", status=None) is not None
