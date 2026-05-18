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
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.sse import SseServerTransport

from approvals import approve_action_by_id, broadcast_pending_actions, reject_action_by_id
from db import store
from mcp_registry import initialization_options, mcp_server
from models.config import load_app_config
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


app = FastAPI(title="DevOps AI Agent", version="0.3.0", lifespan=lifespan)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "phase": 3}


@app.get("/api/incidents")
async def api_incidents() -> dict:
    incidents = await store.list_incidents(limit=50)
    return {"success": True, "incidents": incidents}


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
    await websocket.send_json({"type": "connected", "phase": 3})
    try:
        await _send_latest_snapshots(websocket)
        for row in await store.list_pending_actions():
            await websocket.send_json(
                {
                    "type": "action_pending",
                    "action": {
                        "id": row["id"],
                        "incident_id": row.get("incident_id"),
                        "action_type": row["action_type"],
                        "description": row["description"],
                        "rationale": row["rationale"],
                        "risk_tier": row["risk_tier"],
                        "rollback_plan": row["rollback_plan"],
                        "parameters": row.get("parameters") or {},
                        "status": row.get("status"),
                        "created_at": row.get("created_at"),
                    },
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
                )
                await websocket.send_json({"type": "approve_result", **result})
            elif msg_type == "reject_action":
                result = await reject_action_by_id(
                    data.get("action_id", ""),
                    data.get("feedback", ""),
                )
                await websocket.send_json({"type": "reject_result", **result})
            elif msg_type == "request_handoff":
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "request_handoff available from Phase 4",
                    }
                )
            else:
                await websocket.send_json(
                    {"type": "error", "message": f"Unknown message type: {msg_type}"}
                )
    except WebSocketDisconnect:
        pass
    finally:
        await unregister(websocket)


def _mount_dashboard() -> None:
    if DASHBOARD_DIST.is_dir() and (DASHBOARD_DIST / "index.html").is_file():
        app.mount("/", StaticFiles(directory=str(DASHBOARD_DIST), html=True), name="dashboard")
        logger.info("Serving dashboard from %s", DASHBOARD_DIST)
    else:
        logger.warning(
            "Dashboard not built. Run: cd dashboard && npm install && npm run build"
        )


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
