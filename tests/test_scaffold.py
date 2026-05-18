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
    assert data["phase"] == 6


@pytest.mark.asyncio
async def test_api_incidents_not_shadowed_by_static() -> None:
    from server import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/incidents")
    assert response.status_code == 200
    body = response.json()
    assert body.get("success") is True
    assert "incidents" in body


def test_servers_example_config_loads() -> None:
    """Validates committed example schema (no real hosts required)."""
    config_path = (
        Path(__file__).resolve().parent.parent / "config" / "servers.yaml.example"
    )
    cfg = load_servers_config(config_path)
    droplet = next((s for s in cfg.servers if s.id == "droplet"), None)
    linode = next((s for s in cfg.servers if s.id == "linode"), None)
    assert droplet is not None
    assert linode is not None
    assert any(svc.name == "test-nginx" for svc in droplet.services)
    assert any(svc.name == "FlexInk" for svc in linode.services)
    assert "primary DB" in cfg.protected_services
