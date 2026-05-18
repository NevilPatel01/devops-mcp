"""Setup status API tests."""

from pathlib import Path
import pytest
from httpx import ASGITransport, AsyncClient

from server import app, build_setup_status


@pytest.mark.asyncio
async def test_setup_status_endpoint() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/setup/status")
    assert response.status_code == 200
    data = response.json()
    assert data["phase"] == 6
    assert isinstance(data["servers_configured"], bool)
    assert isinstance(data["repos_configured"], bool)
    assert isinstance(data["repos_count"], int)
    assert isinstance(data["anthropic_configured"], bool)
    assert isinstance(data["github_configured"], bool)
    assert isinstance(data["dashboard_built"], bool)


def test_build_setup_status_env_flags(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-...")
    monkeypatch.setenv("GITHUB_TOKEN", "github_pat_...")
    monkeypatch.setenv("SERVERS_CONFIG_PATH", str(tmp_path / "missing-servers.yaml"))
    monkeypatch.setenv("REPOS_CONFIG_PATH", str(tmp_path / "missing-repos.yaml"))

    status = build_setup_status()
    assert status["anthropic_configured"] is False
    assert status["github_configured"] is False
    assert status["servers_configured"] is False
    assert status["repos_configured"] is False
    assert status["repos_count"] == 0

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real-key-value")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_real_token_value")
    status = build_setup_status()
    assert status["anthropic_configured"] is True
    assert status["github_configured"] is True
