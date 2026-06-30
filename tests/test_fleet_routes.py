"""Fleet API tests."""

import pytest
from httpx import ASGITransport, AsyncClient

from db import store
from server import app


@pytest.mark.asyncio
async def test_fleet_overview_empty() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/fleet/overview")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "sites_total" in data["stats"]


@pytest.mark.asyncio
async def test_fleet_sites_list() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/fleet/sites")
    assert response.status_code == 200
    assert response.json()["success"] is True


@pytest.mark.asyncio
async def test_create_site_without_compose_file(tmp_path) -> None:
    await store.init_db(tmp_path / "fleet.db")
    await store.upsert_managed_server(
        "test-vps",
        label="Test VPS",
        host="203.0.113.10",
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/fleet/sites",
            json={
                "name": "example.com",
                "server_id": "test-vps",
                "url": "https://example.com",
                "service_name": "web",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["site"]["service_name"] == "web"
    assert data["site"]["compose_file"] in (None, "")

    server = await store.get_managed_server("test-vps")
    assert any(s.get("name") == "web" for s in server.get("services") or [])
    assert server["services"][0].get("compose_file") in ("", None)
