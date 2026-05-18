"""Phase 0 scaffold tests."""

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from db import store
from models.config import load_servers_config


@pytest.mark.asyncio
async def test_init_db(tmp_path: Path) -> None:
    db_file = tmp_path / "test.db"
    await store.init_db(db_file)
    servers = await store.list_servers()
    assert servers == []
    await store.close_db()


@pytest.mark.asyncio
async def test_health_endpoint() -> None:
    from server import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["phase"] == 3


def test_servers_config_loads() -> None:
    """Requires config/servers.yaml (local, gitignored)."""
    config_path = Path(__file__).resolve().parent.parent / "config" / "servers.yaml"
    if not config_path.exists():
        pytest.skip("config/servers.yaml not present")
    cfg = load_servers_config(config_path)
    linode = next((s for s in cfg.servers if s.id == "linode"), None)
    assert linode is not None
    assert linode.host
    assert any(svc.name == "FlexInk" for svc in linode.services)
