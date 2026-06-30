"""REST API for fleet onboarding — servers, sites, settings."""

from __future__ import annotations

from typing import Any
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from db import store
from fleet_sync import (
    managed_row_to_server_config,
    rebuild_servers_yaml,
    save_uploaded_key,
    slugify,
)
from onboarding import (
    discover_compose_files,
    list_remote_containers,
    test_ssh_connection,
)
from tools import executor as exec_tools
from tools import infrastructure as infra_tools
from uptime_checker import probe_site_by_id

router = APIRouter(prefix="/api/fleet", tags=["fleet"])


class SshTestBody(BaseModel):
    host: str
    port: int = 22
    user: str = "root"
    ssh_key_path: str | None = None
    ssh_private_key: str | None = None


class ServerCreateBody(BaseModel):
    id: str | None = None
    label: str
    host: str
    port: int = 22
    user: str = "root"
    ssh_key_path: str | None = None
    ssh_private_key: str | None = None
    services: list[dict[str, Any]] = Field(default_factory=list)


class SiteCreateBody(BaseModel):
    id: str | None = None
    client_name: str | None = None
    name: str
    url: str | None = None
    server_id: str
    compose_file: str | None = None
    service_name: str | None = None
    environment: str = "production"
    repo_id: str | None = None
    sensitive: bool = False


class SettingsBody(BaseModel):
    slack_webhook_url: str | None = None
    alert_email: str | None = None
    anthropic_api_key: str | None = None


def _resolve_key_path(body: SshTestBody | ServerCreateBody, server_id: str) -> str:
    if body.ssh_private_key:
        return save_uploaded_key(server_id, body.ssh_private_key)
    return body.ssh_key_path or "~/.ssh/id_ed25519"


@router.get("/servers")
async def list_servers() -> dict:
    rows = await store.list_managed_servers()
    return {"success": True, "servers": rows}


@router.post("/servers/test")
async def api_test_ssh(body: SshTestBody) -> dict:
    sid = slugify(body.host)
    key_path = _resolve_key_path(body, sid)
    return await test_ssh_connection(
        host=body.host.strip(),
        port=body.port,
        user=body.user,
        ssh_key_path=key_path,
    )


@router.post("/servers/discover")
async def api_discover(body: SshTestBody) -> dict:
    sid = slugify(body.host)
    key_path = _resolve_key_path(body, sid)
    return await discover_compose_files(
        host=body.host.strip(),
        port=body.port,
        user=body.user,
        ssh_key_path=key_path,
    )


@router.get("/servers/{server_id}/containers")
async def api_containers(server_id: str) -> dict:
    row = await store.get_managed_server(server_id)
    if not row:
        raise HTTPException(status_code=404, detail="Server not found")
    server = managed_row_to_server_config(row)
    return await list_remote_containers(server)


@router.post("/servers")
async def api_create_server(body: ServerCreateBody) -> dict:
    server_id = slugify(body.id or body.label or body.host)
    key_path = _resolve_key_path(body, server_id)

    test = await test_ssh_connection(
        host=body.host.strip(),
        port=body.port,
        user=body.user,
        ssh_key_path=key_path,
    )
    if not test.get("success"):
        return {"success": False, "error": test.get("error", "SSH test failed")}

    await store.upsert_managed_server(
        server_id,
        label=body.label.strip(),
        host=body.host.strip(),
        port=body.port,
        ssh_user=body.user,
        ssh_key_path=key_path,
        services=body.services,
    )
    await store.upsert_server(server_id, body.label.strip(), body.host.strip(), status="unknown")
    await rebuild_servers_yaml()

    row = await store.get_managed_server(server_id)
    return {"success": True, "server": row, "ssh_test": test}


@router.delete("/servers/{server_id}")
async def api_delete_server(server_id: str) -> dict:
    if not await store.get_managed_server(server_id):
        raise HTTPException(status_code=404, detail="Server not found")
    await store.delete_managed_server(server_id)
    await rebuild_servers_yaml()
    return {"success": True}


@router.get("/sites")
async def api_list_sites() -> dict:
    sites = await store.list_sites()
    servers = {s["id"]: s for s in await store.list_managed_servers()}
    enriched = []
    for site in sites:
        srv = servers.get(site["server_id"], {})
        snap = await store.get_latest_snapshot(site["server_id"])
        enriched.append(
            {
                **site,
                "server_label": srv.get("label"),
                "server_host": srv.get("host"),
                "server_status": (await store.get_server(site["server_id"]) or {}).get(
                    "status", "unknown"
                ),
                "cpu_percent": snap.get("cpu_percent") if snap else None,
                "memory_percent": snap.get("memory_percent") if snap else None,
            }
        )
    return {"success": True, "sites": enriched}


@router.post("/sites")
async def api_create_site(body: SiteCreateBody) -> dict:
    if not await store.get_managed_server(body.server_id):
        return {"success": False, "error": f"Unknown server_id: {body.server_id}"}

    site_id = slugify(body.id or body.name)
    compose_file = (body.compose_file or "").strip() or None
    service_name = (body.service_name or "").strip() or None

    await store.upsert_site(
        site_id,
        name=body.name.strip(),
        server_id=body.server_id,
        client_name=(body.client_name or "").strip() or None,
        url=(body.url or "").strip() or None,
        compose_file=compose_file,
        service_name=service_name,
        environment=body.environment,
        repo_id=body.repo_id,
        sensitive=body.sensitive,
    )

    # Register container on server for poller/agent (compose path optional)
    if service_name:
        row = await store.get_managed_server(body.server_id)
        services = list(row.get("services") or [])
        names = {s.get("name") for s in services}
        if service_name not in names:
            services.append(
                {
                    "name": service_name,
                    "compose_file": compose_file or "",
                    "sensitive": body.sensitive,
                    "health_check_url": body.url,
                }
            )
            await store.upsert_managed_server(
                body.server_id,
                label=row["label"],
                host=row["host"],
                port=row.get("port") or 22,
                ssh_user=row.get("ssh_user") or "root",
                ssh_key_path=row.get("ssh_key_path") or "~/.ssh/id_ed25519",
                services=services,
                thresholds=row.get("thresholds"),
            )
            await rebuild_servers_yaml()

    site = await store.get_site(site_id)
    return {"success": True, "site": site}


@router.delete("/sites/{site_id}")
async def api_delete_site(site_id: str) -> dict:
    if not await store.get_site(site_id):
        raise HTTPException(status_code=404, detail="Site not found")
    await store.delete_site(site_id)
    return {"success": True}


@router.post("/sites/{site_id}/probe")
async def api_probe_site(site_id: str) -> dict:
    result = await probe_site_by_id(site_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Probe failed"))
    return result


@router.get("/sites/{site_id}/logs")
async def api_site_logs(site_id: str, lines: int = 80) -> dict:
    site = await store.get_site(site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    container = site.get("service_name")
    if not container:
        return {"success": False, "error": "No container/service mapped to this site"}
    tail = min(max(lines, 10), 500)
    result = await infra_tools.get_container_logs(
        site["server_id"], container, tail=tail
    )
    return result


@router.post("/sites/{site_id}/restart")
async def api_restart_site(site_id: str) -> dict:
    site = await store.get_site(site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    container = site.get("service_name")
    if not container:
        return {"success": False, "error": "No container/service mapped — edit site config"}
    action_id = f"manual-{uuid.uuid4().hex[:10]}"
    return await exec_tools.restart_container(
        site["server_id"],
        container,
        action_id,
        approved=True,
        service_name=container,
    )


@router.get("/settings")
async def api_get_settings() -> dict:
    raw = await store.get_settings()
    return {
        "success": True,
        "settings": {
            "slack_webhook_url": raw.get("slack_webhook_url", ""),
            "alert_email": raw.get("alert_email", ""),
            "anthropic_configured": bool(raw.get("anthropic_api_key")),
        },
    }


@router.put("/settings")
async def api_put_settings(body: SettingsBody) -> dict:
    if body.slack_webhook_url is not None:
        await store.set_setting("slack_webhook_url", body.slack_webhook_url.strip())
    if body.alert_email is not None:
        await store.set_setting("alert_email", body.alert_email.strip())
    if body.anthropic_api_key is not None and body.anthropic_api_key.strip():
        await store.set_setting("anthropic_api_key", body.anthropic_api_key.strip())
    return {"success": True}


@router.get("/overview")
async def api_overview() -> dict:
    sites = await store.list_sites()
    servers = await store.list_managed_servers()
    incidents = await store.list_incidents(limit=10)
    open_incidents = sum(1 for i in incidents if i.get("status") == "open")
    up = sum(1 for s in sites if s.get("uptime_status") == "up")
    down = sum(1 for s in sites if s.get("uptime_status") == "down")
    return {
        "success": True,
        "stats": {
            "sites_total": len(sites),
            "sites_up": up,
            "sites_down": down,
            "servers_total": len(servers),
            "open_incidents": open_incidents,
        },
    }
