"""GitHub cicd tools — mocked, no network."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from models.config import RepoConfig, ReposFile
from tools import cicd


def test_resolve_repo() -> None:
    with patch("tools.cicd.load_repos_config") as mock:
        mock.return_value = ReposFile(
            repos=[RepoConfig(id="api", owner="acme", name="api", default_branch="main")]
        )
        repo = cicd.resolve_repo("api")
    assert repo is not None
    assert repo.owner == "acme"


@pytest.mark.asyncio
async def test_get_latest_workflow_run_no_token() -> None:
    with patch("tools.cicd.resolve_repo") as mock_repo:
        mock_repo.return_value = RepoConfig(id="r", owner="o", name="n")
        with patch("tools.cicd._github_client", return_value=None):
            result = await cicd.get_latest_workflow_run("r")
    assert result["success"] is False
    assert "GITHUB_TOKEN" in result["error"]


@pytest.mark.asyncio
async def test_gather_deploy_context_no_repos() -> None:
    with patch("tools.cicd.load_repos_config") as mock:
        mock.return_value = ReposFile(repos=[])
        ctx = await cicd.gather_deploy_context("fct-droplet", "test-nginx")
    assert ctx["related_deploy"] is None
    assert ctx["repos_checked"] == []


@pytest.mark.asyncio
async def test_correlate_includes_github_when_configured() -> None:
    from tools import incident as incident_tools

    with patch("tools.incident.load_app_config") as mock_cfg:
        from models.config import AppConfig, AutomationConfig, RulesFile, ServersFile

        mock_cfg.return_value = AppConfig(
            servers=ServersFile(),
            rules=RulesFile(automation=AutomationConfig()),
            repos=ReposFile(
                repos=[
                    RepoConfig(
                        id="app",
                        owner="o",
                        name="n",
                        linked_servers=["fct-droplet"],
                        linked_services=["test-nginx"],
                    )
                ]
            ),
        )
        with patch(
            "tools.incident.store.get_snapshots_for_incident_window",
            return_value=[],
        ):
            with patch("tools.incident.store.list_feedback_rules", return_value=[]):
                with patch("tools.incident.store.find_similar_incidents", return_value=[]):
                    with patch(
                        "tools.incident.cicd.gather_deploy_context",
                        return_value={
                            "related_deploy": {"repo_id": "app", "conclusion": "failure"},
                            "github_timeline": [{"repo_id": "app"}],
                            "repos_checked": ["app"],
                        },
                    ):
                        result = await incident_tools.correlate_incident(
                            "fct-droplet", "test-nginx"
                        )
    assert result["success"] is True
    assert result["related_deploy"]["repo_id"] == "app"
