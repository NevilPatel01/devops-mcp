"""Risk-gated execution orchestration + post-action health verification."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from db import store
from models.config import ServerConfig, load_app_config, load_servers_config
from models.incident import ProposedAction
from ssh_client import run_ssh
from tools import executor as exec_tools
from tools import incident as incident_tools
from tools.infrastructure import collect_health_snapshot
from ws_hub import ws_broadcast

logger = logging.getLogger(__name__)

HEALTH_CHECK_DELAY_SECONDS = 3


def _server_by_id(server_id: str) -> ServerConfig | None:
    try:
        cfg = load_servers_config()
    except FileNotFoundError:
        return None
    for s in cfg.servers:
        if s.id == server_id:
            return s
    return None


def _service_config(server: ServerConfig, service_name: str | None):
    if not service_name:
        return None
    for svc in server.services:
        if svc.name == service_name:
            return svc
    return None


async def _verify_container_health(
    server: ServerConfig,
    container_name: str,
    service_name: str | None,
) -> tuple[bool, str]:
    await asyncio.sleep(HEALTH_CHECK_DELAY_SECONDS)
    snap = await collect_health_snapshot(server)
    if not snap.get("success"):
        return False, snap.get("error") or "Health snapshot failed"

    matched = None
    for c in snap.get("containers") or []:
        name = c.get("name", "")
        if name == container_name or container_name in name:
            matched = c
            break
    if not matched:
        return False, f"Container '{container_name}' not found after action"

    status = (matched.get("status") or "").lower()
    if "up" in status and "exited" not in status and "dead" not in status:
        svc = _service_config(server, service_name)
        if svc and svc.health_check_url:
            url = svc.health_check_url
            code, out, err = await run_ssh(
                server,
                f"curl -sf -o /dev/null -w '%{{http_code}}' {url} 2>/dev/null || echo fail",
            )
            if "fail" in (out + err) or code != 0:
                return False, f"health_check_url failed for {url}"
        return True, f"Container healthy: {matched.get('status')}"
    return False, f"Container unhealthy: {matched.get('status')}"


async def _post_action_health_check(action: ProposedAction) -> tuple[bool, str]:
    params = action.parameters or {}
    server_id = params.get("server_id", "")
    server = _server_by_id(server_id)
    if not server:
        return False, f"Unknown server {server_id}"

    container_name = params.get("container_name")
    service_name = params.get("service_name")

    if action.action_type == "restart_container" and container_name:
        return await _verify_container_health(server, container_name, service_name)

    if action.action_type in ("run_compose_command", "scale_service"):
        snap = await collect_health_snapshot(server)
        if not snap.get("success"):
            return False, snap.get("error") or "Post-compose health snapshot failed"
        unhealthy = [
            c.get("name")
            for c in (snap.get("containers") or [])
            if "exited" in (c.get("status") or "").lower()
        ]
        if unhealthy:
            return False, f"Unhealthy containers after compose: {', '.join(unhealthy[:5])}"
        return True, "Compose services running"

    if action.action_type in ("run_ssh_command", "rollback_deployment"):
        if action.action_type == "run_ssh_command":
            return True, "SSH command completed (no automatic health probe)"

    if action.action_type == "rollback_deployment":
        service_name = params.get("service_name")
        if service_name:
            snap = await collect_health_snapshot(server)
            if not snap.get("success"):
                return False, snap.get("error") or "Post-rollback snapshot failed"
            for c in snap.get("containers") or []:
                if service_name.lower() in (c.get("name") or "").lower():
                    status = (c.get("status") or "").lower()
                    if "up" in status and "exited" not in status:
                        return True, f"Service running after rollback: {c.get('status')}"
            return False, "Service not healthy after rollback"
        return True, "Rollback completed"

    return True, "No health check configured for action type"


async def _create_health_failure_incident(
    action: ProposedAction, reason: str
) -> str | None:
    params = action.parameters or {}
    server_id = params.get("server_id", "unknown")
    result = await incident_tools.create_incident(
        server_id,
        "Post-action health check failed",
        (
            f"Action {action.id} ({action.action_type}) ran but verification failed: "
            f"{reason}"
        ),
        "high",
        service_name=params.get("service_name"),
    )
    if result.get("success"):
        await ws_broadcast(
            {
                "type": "incident_created",
                "incident": result.get("incident"),
            }
        )
        return result.get("incident_id")
    return None


async def execute(action: ProposedAction, *, approved: bool = False) -> dict[str, Any]:
    """Run the approved action tool (no health check — use execute_and_finalize)."""
    if not approved:
        return {"success": False, "error": "Action not approved"}

    params = action.parameters or {}
    server_id = params.get("server_id", "")
    action_id = action.id
    risk = (action.risk_tier or "medium").lower()

    try:
        cfg = load_app_config()
        protected = cfg.servers.protected_services
        service_name = params.get("service_name")
        if service_name and service_name in protected:
            return {
                "success": False,
                "error": f"Service '{service_name}' is in protected_services",
            }

        if risk in ("medium", "high") and action.action_type == "restart_container":
            pass
        elif risk == "high" and action.action_type != "run_ssh_command":
            return {
                "success": False,
                "error": "HIGH risk requires explicit run_ssh_command action type",
            }

        result: dict[str, Any]
        if action.action_type == "restart_container":
            result = await exec_tools.restart_container(
                server_id,
                params.get("container_name", ""),
                action_id,
                approved=True,
                service_name=service_name,
            )
        elif action.action_type == "run_compose_command":
            result = await exec_tools.run_compose_command(
                server_id,
                params.get("compose_file", ""),
                params.get("command", ""),
                action_id,
                approved=True,
                service_name=service_name,
            )
        elif action.action_type == "run_ssh_command":
            result = await exec_tools.run_ssh_command(
                server_id,
                params.get("command", ""),
                action_id,
                approved=True,
                risk_tier=risk,
            )
        elif action.action_type == "scale_service":
            result = await exec_tools.scale_service(
                server_id,
                params.get("compose_file", ""),
                params.get("service_name", ""),
                int(params.get("replicas", 1)),
                action_id,
                approved=True,
            )
        elif action.action_type == "rollback_deployment":
            result = await exec_tools.rollback_deployment(
                server_id,
                params.get("service_name", ""),
                params.get("compose_file", ""),
                action_id,
                approved=True,
            )
        else:
            return {
                "success": False,
                "error": f"Unknown action_type: {action.action_type}",
            }

        await store.insert_action_log(
            action_id,
            result.get("output", "") or result.get("error", ""),
            bool(result.get("success")),
        )
        if result.get("success"):
            await store.update_action_status(action_id, "executed")
        else:
            await store.update_action_status(action_id, "failed")
        return result
    except Exception as exc:
        logger.exception("Executor error for %s", action_id)
        await store.update_action_status(action_id, "failed")
        return {"success": False, "error": str(exc)}


async def execute_and_finalize(action: ProposedAction) -> dict[str, Any]:
    """Execute, verify health, resolve incident or open a new one on failure."""
    await ws_broadcast(
        {
            "type": "action_executing",
            "action_id": action.id,
            "action_type": action.action_type,
            "description": action.description,
        }
    )

    result = await execute(action, approved=True)
    if not result.get("success"):
        await ws_broadcast(
            {
                "type": "error",
                "message": result.get("error", "Execution failed"),
                "action_id": action.id,
            }
        )
        return result

    health_ok, health_msg = await _post_action_health_check(action)
    result["health_ok"] = health_ok
    result["health_message"] = health_msg

    if health_ok:
        postmortem_md = None
        if action.incident_id:
            await store.update_incident_status(action.incident_id, "resolved")
            from runbook_engine import maybe_create_draft_runbook

            await maybe_create_draft_runbook(action.incident_id, action)
            pm = await incident_tools.draft_postmortem(action.incident_id)
            if pm.get("success"):
                postmortem_md = pm.get("postmortem_markdown")
            await ws_broadcast(
                {
                    "type": "incident_resolved",
                    "incident_id": action.incident_id,
                    "postmortem_markdown": postmortem_md,
                }
            )
        await ws_broadcast(
            {
                "type": "action_executed",
                "action_id": action.id,
                "output": result.get("output", ""),
                "health_ok": True,
                "postmortem_markdown": postmortem_md,
            }
        )
    else:
        await _log_line(action.id, f"\n[health check failed] {health_msg}\n")
        followup_id = await _create_health_failure_incident(action, health_msg)
        await ws_broadcast(
            {
                "type": "action_executed",
                "action_id": action.id,
                "output": result.get("output", ""),
                "health_ok": False,
                "health_message": health_msg,
                "followup_incident_id": followup_id,
            }
        )
        logger.warning(
            "Health check failed for action %s: %s (no auto-rollback)",
            action.id,
            health_msg,
        )

    return result


async def _log_line(action_id: str, line: str) -> None:
    await ws_broadcast(
        {"type": "action_log_line", "action_id": action_id, "line": line}
    )
