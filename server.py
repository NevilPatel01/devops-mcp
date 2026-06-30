"""
DevOps AI Agent — entry point.

FastAPI + WebSocket + static dashboard + MCP SSE.
Run: python server.py
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.sse import SseServerTransport
from pydantic import BaseModel, Field

from approvals import (
    _serialize_action,
    approve_action_by_id,
    broadcast_pending_actions,
    reject_action_by_id,
)
from db import store
from fleet_routes import router as fleet_router
from fleet_sync import import_yaml_to_db_if_empty, rebuild_servers_yaml
from mcp_registry import initialization_options, mcp_server
from models.config import load_app_config, load_repos_config
from poller import start_poller, stop_poller
from ssh_client import check_port_available
from uptime_checker import start_uptime_checker, stop_uptime_checker
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
    await import_yaml_to_db_if_empty()
    await rebuild_servers_yaml()
    try:
        cfg = load_app_config()
        for s in cfg.servers.servers:
            await store.upsert_server(s.id, s.label, s.host, status="unknown")
        logger.info("Loaded %d server(s) from config", len(cfg.servers.servers))
    except FileNotFoundError as exc:
        logger.warning("%s", exc)
    await start_poller()
    await start_uptime_checker()
    await broadcast_pending_actions()
    yield
    await stop_uptime_checker()
    await stop_poller()
    await store.close_db()


app = FastAPI(title="DevOps MCP", version="1.0.0", lifespan=lifespan)
app.include_router(fleet_router)


def _anthropic_configured() -> bool:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    return bool(api_key) and not api_key.startswith("sk-ant-...")


def _github_configured() -> bool:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    return bool(token) and not token.startswith("github_pat_...")


async def build_setup_status() -> dict:
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
    sites = await store.list_sites()
    sites_count = len(sites)
    return {
        "phase": 8,
        "product": "fleet",
        "servers_configured": servers_configured,
        "servers_in_db": await store.count_managed_servers(),
        "sites_count": sites_count,
        "repos_configured": repos_configured,
        "repos_count": repos_count,
        "anthropic_configured": _anthropic_configured(),
        "github_configured": _github_configured(),
        "dashboard_built": (DASHBOARD_DIST / "index.html").is_file(),
    }


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "phase": 8}


@app.get("/api/setup/status")
async def setup_status() -> dict:
    return await build_setup_status()


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


class FalsePositiveBody(BaseModel):
    reason: str | None = None
    suppress_similar_hours: int | None = Field(default=None, ge=0, le=168)


@app.post("/api/incidents/{incident_id}/false-positive")
async def api_false_positive(
    incident_id: str,
    body: FalsePositiveBody = Body(default_factory=FalsePositiveBody),
) -> dict:
    from false_positive_handler import process_false_positive
    from ws_hub import ws_broadcast

    result = await process_false_positive(
        incident_id,
        reason=body.reason,
        suppress_similar_hours=body.suppress_similar_hours,
        actor="dashboard",
    )
    if result.get("success") and result.get("suppression_id"):
        await ws_broadcast(
            {
                "type": "suppression_created",
                "incident_id": incident_id,
                "suppression_id": result["suppression_id"],
            }
        )
    return result


@app.get("/api/services/fatigue")
async def api_services_fatigue() -> dict:
    scores = await store.list_alert_fatigue()
    return {"success": True, "services": scores}


@app.get("/api/suppressions")
async def api_list_suppressions(server_id: str | None = None) -> dict:
    patterns = await store.list_suppression_patterns(server_id, active_only=True)
    return {"success": True, "patterns": patterns, "count": len(patterns)}


@app.delete("/api/suppressions/{pattern_id}")
async def api_delete_suppression(pattern_id: int) -> dict:
    ok = await store.delete_suppression_pattern(pattern_id)
    if not ok:
        return {"success": False, "error": "Not found"}
    return {"success": True}


@app.post("/api/incidents/{incident_id}/postmortem")
async def api_draft_postmortem(incident_id: str) -> dict:
    from tools import incident as incident_tools

    return await incident_tools.draft_postmortem(incident_id)


class RunbookApproveBody(BaseModel):
    auto_executable: bool = False
    approved_by: str = "dashboard"


class RunbookStepsBody(BaseModel):
    steps: list[dict]


@app.get("/api/runbooks")
async def api_list_runbooks(
    service_name: str | None = None,
    status: str | None = None,
) -> dict:
    from tools import incident as incident_tools

    return await incident_tools.list_runbooks(service_name=service_name, status=status)


@app.get("/api/runbooks/{runbook_id}")
async def api_get_runbook(runbook_id: str) -> JSONResponse:
    row = await store.get_runbook_by_id(runbook_id)
    if not row:
        return JSONResponse({"success": False, "error": "Not found"}, status_code=404)
    return JSONResponse({"success": True, "runbook": row})


@app.post("/api/runbooks/{runbook_id}/approve")
async def api_approve_runbook(
    runbook_id: str,
    body: RunbookApproveBody = Body(default_factory=RunbookApproveBody),
) -> dict:
    from tools import incident as incident_tools
    from ws_hub import ws_broadcast

    result = await incident_tools.approve_runbook(
        runbook_id,
        auto_executable=body.auto_executable,
        approved_by=body.approved_by,
    )
    if result.get("success"):
        await ws_broadcast(
            {
                "type": "runbook_approved",
                "runbook_id": runbook_id,
                "runbook": result.get("runbook"),
            }
        )
    return result


@app.post("/api/incidents/{incident_id}/generate-runbook")
async def api_generate_runbook(incident_id: str) -> dict:
    from tools import incident as incident_tools
    from ws_hub import ws_broadcast

    result = await incident_tools.propose_runbook_from_incident(incident_id)
    if result.get("success"):
        await ws_broadcast(
            {
                "type": "runbook_draft_created",
                "incident_id": incident_id,
                "runbook": result.get("runbook"),
            }
        )
    return result


@app.put("/api/runbooks/{runbook_id}")
async def api_update_runbook(
    runbook_id: str,
    body: RunbookStepsBody,
) -> JSONResponse:
    row = await store.update_runbook_steps(runbook_id, body.steps)
    if not row:
        return JSONResponse(
            {"success": False, "error": "Not found or not a draft"},
            status_code=404,
        )
    return JSONResponse({"success": True, "runbook": row})


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


@app.post("/api/terraform/analyze")
async def api_terraform_analyze(request: Request) -> JSONResponse:
    from tools import terraform as terraform_tools

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse(
            {"success": False, "error": "JSON body required"}, status_code=400
        )
    plan_json = body.get("plan_json")
    if plan_json is not None and not isinstance(plan_json, str):
        plan_json = json.dumps(plan_json)
    result = await terraform_tools.analyze_terraform_plan(
        plan_json=plan_json,
        plan_path=body.get("plan_path"),
        rules_profile=body.get("rules_profile"),
    )
    status = 200 if result.get("success") else 400
    return JSONResponse(result, status_code=status)


@app.get("/api/terraform/analyses/{analysis_id}")
async def api_terraform_analysis(analysis_id: str) -> JSONResponse:
    from tools import terraform as terraform_tools

    result = await terraform_tools.get_terraform_analysis(analysis_id)
    if not result.get("success"):
        return JSONResponse(result, status_code=404)
    return JSONResponse(result)


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
    await websocket.send_json({"type": "connected", "phase": 8})
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
