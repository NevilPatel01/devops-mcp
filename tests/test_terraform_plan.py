"""Phase 5 — Terraform plan analyser tests."""

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from db import store
from tools import terraform

FIXTURES = Path(__file__).parent / "fixtures" / "terraform"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_parse_and_score_create() -> None:
    plan = _load_fixture("plan_create.json")
    rules = terraform.load_terraform_rules()
    records, _ = terraform.parse_plan_json(plan)
    assert len(records) == 1
    scored = terraform.score_resource_change(records[0], rules)
    assert scored["action"] == "create"
    assert scored["risk_score"] == 2.0


def test_flagged_delete() -> None:
    plan = _load_fixture("plan_delete.json")
    rules = terraform.load_terraform_rules()
    records, _ = terraform.parse_plan_json(plan)
    scored = terraform.score_resource_change(records[0], rules)
    assert scored["action"] == "delete"
    assert scored["risk_score"] >= rules["risk_weights"]["delete"]
    assert scored["flagged"] is True


def test_naming_violations() -> None:
    plan = _load_fixture("plan_naming_violation.json")
    rules = terraform.load_terraform_rules()
    records, _ = terraform.parse_plan_json(plan)
    violations: list[dict] = []
    for record in records:
        violations.extend(terraform.check_naming_conventions(record, rules))
    assert len(violations) >= 2
    assert any(
        "azurerm_linux_virtual_machine_prefix" in v["rule"] for v in violations
    )


def test_analyze_plan_data_summary() -> None:
    plan = _load_fixture("plan_delete.json")
    result = terraform.analyze_plan_data(plan)
    assert result["success"] is True
    assert result["overall_risk_score"] >= 10.0 or result["overall_risk_score"] == 10.0
    assert len(result["flagged_deletes"]) >= 1
    assert "Terraform plan summary" in result["summary_markdown"]


def test_invalid_json_returns_error() -> None:
    result = terraform.analyze_plan_data({"not_a_plan": True})
    assert result["success"] is False


@pytest.mark.asyncio
async def test_analyze_terraform_plan_mcp(tmp_path: Path) -> None:
    await store.init_db(tmp_path / "tf.db")
    plan = _load_fixture("plan_create.json")
    result = await terraform.analyze_terraform_plan(
        plan_json=json.dumps(plan),
    )
    assert result["success"] is True
    assert result["analysis_id"]
    cached = await terraform.get_terraform_analysis(result["analysis_id"])
    assert cached["success"] is True
    assert cached["summary_markdown"]
    await store.close_db()


@pytest.mark.asyncio
async def test_invalid_json_mcp() -> None:
    result = await terraform.analyze_terraform_plan(plan_json="{not json")
    assert result["success"] is False
    assert "Invalid JSON" in result["error"]


@pytest.mark.asyncio
async def test_api_terraform_analyze() -> None:
    from server import app

    plan = _load_fixture("plan_create.json")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/terraform/analyze",
            json={"plan_json": json.dumps(plan)},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["changes"]
