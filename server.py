"""
DevOps AI Agent — entry point.

FastAPI + WebSocket + static dashboard + MCP SSE.
Run: python server.py
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.sse import SseServerTransport

from approvals import (
    _serialize_action,
    approve_action_by_id,
    broadcast_pending_actions,
    reject_action_by_id,
)
from db import store
from mcp_registry import initialization_options, mcp_server
from models.config import load_app_config, load_repos_config
from poller import start_poller, stop_poller
from ssh_client import check_port_available
from ws_hub import register, unregister

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
DASHBOARD_DIST = ROOT / "dashboard" / "dist"
FAVICON_PATH = DASHBOARD_DIST / "favicon.svg"

_sse_transport = SseServerTransport("/mcp/messages")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await store.init_db()
    await store.prune_snapshots_older_than_days(7)
    await store.prune_compliance_audit_older_than_days(90)
    try:
        cfg = load_app_config()
        for s in cfg.servers.servers:
            await store.upsert_server(s.id, s.label, s.host, status="unknown")
        logger.info("Loaded %d server(s) from config", len(cfg.servers.servers))
    except FileNotFoundError as exc:
        logger.warning("%s", exc)
    await start_poller()
    await broadcast_pending_actions()
    yield
    await stop_poller()
    await store.close_db()


app = FastAPI(title="DevOps AI Agent", version="0.4.0", lifespan=lifespan)


def _anthropic_configured() -> bool:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    return bool(api_key) and not api_key.startswith("sk-ant-...")


def _github_configured() -> bool:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    return bool(token) and not token.startswith("github_pat_...")


def build_setup_status() -> dict:
    """Return setup checklist fields for /api/setup/status and tests."""
    config_dir = ROOT / "config"
    servers_path = Path(
        os.getenv("SERVERS_CONFIG_PATH", str(config_dir / "servers.yaml"))
    )
    repos_path = Path(os.getenv("REPOS_CONFIG_PATH", str(config_dir / "repos.yaml")))
    servers_configured = servers_path.is_file()
    repos_configured = repos_path.is_file()
    repos_count = 0
    if repos_configured:
        try:
            repos_count = len(load_repos_config(repos_path).repos)
        except Exception:
            repos_count = 0
    return {
        "phase": 6,
        "servers_configured": servers_configured,
        "repos_configured": repos_configured,
        "repos_count": repos_count,
        "anthropic_configured": _anthropic_configured(),
        "github_configured": _github_configured(),
        "dashboard_built": (DASHBOARD_DIST / "index.html").is_file(),
    }


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "phase": 6}


@app.get("/api/setup/status")
async def setup_status() -> dict:
    return build_setup_status()


@app.get("/api/incidents")
async def api_incidents() -> dict:
    incidents = await store.list_incidents(limit=50)
    return {"success": True, "incidents": incidents}


@app.get("/api/incidents/{incident_id}")
async def api_incident_detail(incident_id: str) -> JSONResponse:
    incident = await store.get_incident(incident_id)
    if not incident:
        return JSONResponse(
            {"success": False, "error": "Not found"}, status_code=404
        )
    actions = await store.get_actions_for_incident(incident_id)
    logs_by_action = {}
    for action in actions:
        logs_by_action[action["id"]] = await store.get_action_logs(action["id"])
    return JSONResponse(
        {
            "success": True,
            "incident": incident,
            "actions": actions,
            "action_logs": logs_by_action,
        }
    )


@app.post("/api/incidents/{incident_id}/false-positive")
async def api_false_positive(incident_id: str) -> dict:
    row = await store.mark_incident_false_positive(incident_id)
    if not row:
        return {"success": False, "error": "Not found"}
    return {"success": True, "incident": row}


@app.post("/api/incidents/{incident_id}/postmortem")
async def api_draft_postmortem(incident_id: str) -> dict:
    from tools import incident as incident_tools

    return await incident_tools.draft_postmortem(incident_id)


@app.get("/api/handoff")
async def api_handoff() -> dict:
    from tools import incident as incident_tools

    return await incident_tools.get_oncall_handoff()


@app.get("/api/incidents/{incident_id}/compliance")
async def api_incident_compliance(incident_id: str) -> JSONResponse:
    incident = await store.get_incident(incident_id)
    if not incident:
        return JSONResponse(
            {"success": False, "error": "Not found"}, status_code=404
        )
    audit = await store.list_compliance_audit(incident_id=incident_id, hours=168)
    return JSONResponse(
        {
            "success": True,
            "incident_id": incident_id,
            "is_sensitive": bool(incident.get("is_sensitive")),
            "compliance_profile": incident.get("compliance_profile") or "none",
            "audit_trail": audit,
        }
    )


@app.get("/api/compliance/audit")
async def api_compliance_audit(hours: int = 24) -> dict:
    entries = await store.list_compliance_audit(hours=max(1, min(hours, 168)))
    return {"success": True, "entries": entries}


@app.get("/api/config/services")
async def api_config_services() -> dict:
    try:
        cfg = load_app_config()
    except FileNotFoundError as exc:
        return {"success": False, "error": str(exc), "servers": []}
    servers_out = []
    for srv in cfg.servers.servers:
        servers_out.append(
            {
                "server_id": srv.id,
                "label": srv.label,
                "services": [
                    {
                        "name": svc.name,
                        "sensitive": svc.sensitive,
                        "compliance_profile": svc.compliance_profile
                        or (
                            cfg.servers.compliance.default_profile
                            if svc.sensitive
                            else "none"
                        ),
                    }
                    for svc in srv.services
                ],
            }
        )
    return {
        "success": True,
        "protected_services": cfg.servers.protected_services,
        "default_compliance_profile": cfg.servers.compliance.default_profile,
        "servers": servers_out,
    }


@app.get("/api/servers/{server_id}/snapshots")
async def api_snapshot_history(server_id: str, limit: int = 48) -> dict:
    history = await store.get_snapshot_history(server_id, limit=min(limit, 200))
    return {
        "success": True,
        "server_id": server_id,
        "snapshots": [
            {
                "captured_at": s.get("captured_at"),
                "cpu_percent": s.get("cpu_percent"),
                "memory_percent": s.get("memory_percent"),
                "disk_percent": s.get("disk_percent"),
            }
            for s in reversed(history)
        ],
    }


@app.get("/favicon.ico", include_in_schema=False)
@app.get("/favicon.svg", include_in_schema=False)
async def favicon() -> FileResponse:
    if FAVICON_PATH.is_file():
        return FileResponse(FAVICON_PATH, media_type="image/svg+xml")
    fallback = ROOT / "dashboard" / "public" / "favicon.svg"
    return FileResponse(fallback, media_type="image/svg+xml")


@app.get("/mcp")
async def mcp_sse(request: Request) -> None:
    async with _sse_transport.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await mcp_server.run(
            streams[0],
            streams[1],
            initialization_options(),
        )


@app.post("/mcp/messages")
async def mcp_messages(request: Request) -> None:
    await _sse_transport.handle_post_message(
        request.scope, request.receive, request._send
    )


async def _send_latest_snapshots(websocket: WebSocket) -> None:
    for row in await store.list_servers():
        snap = await store.get_latest_snapshot(row["id"])
        if not snap:
            continue
        containers = snap.get("container_statuses") or []
        await websocket.send_json(
            {
                "type": "snapshot_update",
                "server_id": row["id"],
                "data": {
                    "server_id": row["id"],
                    "label": row["label"],
                    "status": row.get("status", "unknown"),
                    "cpu_percent": snap.get("cpu_percent"),
                    "memory_percent": snap.get("memory_percent"),
                    "disk_percent": snap.get("disk_percent"),
                    "container_count": len(containers),
                    "containers": containers,
                    "captured_at": snap.get("captured_at"),
                },
            }
        )


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await register(websocket)
    await websocket.send_json({"type": "connected", "phase": 6})
    try:
        await _send_latest_snapshots(websocket)
        for row in await store.list_pending_actions():
            await websocket.send_json(
                {
                    "type": "action_pending",
                    "action": _serialize_action(row),
                }
            )
    except Exception as exc:
        logger.warning("Could not send initial state: %s", exc)
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            elif msg_type == "approve_action":
                result = await approve_action_by_id(
                    data.get("action_id", ""),
                    source="dashboard",
                    confirm_text=data.get("confirm_text"),
                    compliance_confirm_text=data.get("compliance_confirm_text"),
                )
                await websocket.send_json({"type": "approve_result", **result})
            elif msg_type == "reject_action":
                result = await reject_action_by_id(
                    data.get("action_id", ""),
                    data.get("feedback", ""),
                )
                await websocket.send_json({"type": "reject_result", **result})
            elif msg_type == "request_handoff":
                from tools import incident as incident_tools

                handoff = await incident_tools.get_oncall_handoff()
                await websocket.send_json(
                    {"type": "handoff_ready", **handoff}
                )
            else:
                await websocket.send_json(
                    {"type": "error", "message": f"Unknown message type: {msg_type}"}
                )
    except WebSocketDisconnect:
        pass
    finally:
        await unregister(websocket)


_RESERVED_SPA_PREFIXES = frozenset({"api", "ws", "mcp"})


def _mount_dashboard() -> None:
    """Serve Vite build without mounting '/' (that shadows /api/* on some Starlette versions)."""
    if not DASHBOARD_DIST.is_dir() or not (DASHBOARD_DIST / "index.html").is_file():
        logger.warning(
            "Dashboard not built. Run: cd dashboard && npm install && npm run build"
        )
        return

    assets_dir = DASHBOARD_DIST / "assets"
    if assets_dir.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=str(assets_dir)),
            name="dashboard-assets",
        )

    # SPA fallback must be registered last (after /api, /ws, /mcp).
    @app.get("/", include_in_schema=False)
    async def dashboard_index() -> FileResponse:
        return FileResponse(DASHBOARD_DIST / "index.html")

    @app.get("/{spa_path:path}", include_in_schema=False)
    async def dashboard_spa(spa_path: str) -> FileResponse:
        first = spa_path.split("/", 1)[0] if spa_path else ""
        if first in _RESERVED_SPA_PREFIXES:
            raise HTTPException(status_code=404, detail="Not found")
        target = DASHBOARD_DIST / spa_path
        if spa_path and target.is_file():
            return FileResponse(target)
        return FileResponse(DASHBOARD_DIST / "index.html")

    logger.info("Serving dashboard from %s", DASHBOARD_DIST)


_mount_dashboard()


def main() -> None:
    import uvicorn

    host = os.getenv("DASHBOARD_HOST", "127.0.0.1")
    port = int(os.getenv("DASHBOARD_PORT", "8080"))
    try:
        check_port_available(host, port)
    except OSError as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc
    logger.info("Starting DevOps AI Agent on http://%s:%s", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
