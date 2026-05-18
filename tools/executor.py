"""Execution MCP tools — SSH write paths (rollback_deployment is Phase 4)."""

from __future__ import annotations

import logging
import shlex
from typing import Any

from models.config import ServerConfig, load_servers_config
from ssh_client import detect_compose_command, get_compose_command, run_ssh
from tools.infrastructure import collect_health_snapshot, list_containers
from ws_hub import ws_broadcast

logger = logging.getLogger(__name__)


def _get_server(server_id: str) -> ServerConfig | None:
    try:
        cfg = load_servers_config()
    except FileNotFoundError:
        return None
    for s in cfg.servers:
        if s.id == server_id:
            return s
    return None


def _service_for_container(server: ServerConfig, container_name: str) -> str | None:
    name_lower = container_name.lower()
    for svc in server.services:
        if svc.name.lower() in name_lower or name_lower in svc.name.lower():
            return svc.name
    return None


async def _log_line(action_id: str, line: str) -> None:
    await ws_broadcast(
        {"type": "action_log_line", "action_id": action_id, "line": line}
    )


async def _guard_execution(
    server: ServerConfig | None,
    *,
    service_name: str | None,
    container_name: str | None = None,
    approved: bool,
    required_approved: bool = True,
) -> dict[str, Any] | None:
    """Return error dict if execution must not proceed."""
    if required_approved and not approved:
        return {"success": False, "error": "Action requires approval"}
    if not server:
        return {"success": False, "error": "Unknown server"}
    cfg = load_servers_config()
    svc_name = service_name
    if not svc_name and container_name:
        svc_name = _service_for_container(server, container_name)
    if svc_name and svc_name in cfg.protected_services:
        return {
            "success": False,
            "error": f"Service '{svc_name}' is protected — execution blocked",
        }
    if container_name:
        for svc in server.services:
            if svc.sensitive and (
                svc_name == svc.name
                or svc.name.lower() in container_name.lower()
            ):
                return {
                    "success": False,
                    "error": f"Sensitive service '{svc.name}' — execution blocked",
                }
    return None


async def _container_state(server: ServerConfig, container_name: str) -> dict[str, Any]:
    listed = await list_containers(server.id)
    if not listed.get("success"):
        return {"status": "unknown", "error": listed.get("error")}
    for c in listed.get("containers") or []:
        if c.get("name") == container_name or container_name in (c.get("name") or ""):
            return {"status": c.get("status"), "name": c.get("name"), "image": c.get("image")}
    return {"status": "missing"}


async def restart_container(
    server_id: str,
    container_name: str,
    action_id: str,
    approved: bool = False,
    *,
    service_name: str | None = None,
) -> dict[str, Any]:
    try:
        server = _get_server(server_id)
        blocked = await _guard_execution(
            server,
            service_name=service_name,
            container_name=container_name,
            approved=approved,
        )
        if blocked:
            blocked["action_id"] = action_id
            return blocked

        pre_state = await _container_state(server, container_name)
        safe_name = container_name.replace("'", "")
        cmd = f"docker restart '{safe_name}'"
        await _log_line(action_id, f"$ {cmd}\n")
        code, out, err = await run_ssh(server, cmd)
        output = (out or "") + (err or "")
        await _log_line(action_id, output or f"exit {code}\n")
        if code != 0:
            return {
                "success": False,
                "error": err or f"docker restart failed with exit {code}",
                "output": output,
                "action_id": action_id,
                "pre_state": pre_state,
            }
        post_state = await _container_state(server, container_name)
        return {
            "success": True,
            "error": None,
            "output": output,
            "action_id": action_id,
            "pre_state": pre_state,
            "post_state": post_state,
            "container_name": container_name,
        }
    except Exception as exc:
        logger.warning("restart_container failed: %s", exc)
        return {"success": False, "error": str(exc), "action_id": action_id}


async def run_compose_command(
    server_id: str,
    compose_file: str,
    command: str,
    action_id: str,
    approved: bool = False,
    *,
    service_name: str | None = None,
) -> dict[str, Any]:
    try:
        server = _get_server(server_id)
        blocked = await _guard_execution(
            server, service_name=service_name, approved=approved
        )
        if blocked:
            blocked["action_id"] = action_id
            return blocked

        compose = get_compose_command(server_id) or await detect_compose_command(server)
        cmd = f"{compose} -f {shlex.quote(compose_file)} {command}"
        await _log_line(action_id, f"$ {cmd}\n")
        code, out, err = await run_ssh(server, cmd)
        output = (out or "") + (err or "")
        await _log_line(action_id, output or f"exit {code}\n")
        return {
            "success": code == 0,
            "error": None if code == 0 else (err or f"exit {code}"),
            "output": output,
            "exit_code": code,
            "action_id": action_id,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "action_id": action_id}


async def run_ssh_command(
    server_id: str,
    command: str,
    action_id: str,
    approved: bool = False,
    risk_tier: str = "high",
) -> dict[str, Any]:
    try:
        server = _get_server(server_id)
        blocked = await _guard_execution(
            server, service_name=None, approved=approved
        )
        if blocked:
            blocked["action_id"] = action_id
            return blocked
        if risk_tier.lower() == "high" and not approved:
            return {
                "success": False,
                "error": "HIGH risk SSH requires dashboard CONFIRM approval",
                "action_id": action_id,
            }

        await _log_line(action_id, f"$ {command}\n")
        code, out, err = await run_ssh(server, command)
        await _log_line(action_id, (out or "") + (err or "") + f"\n[exit {code}]\n")
        return {
            "success": code == 0,
            "error": None if code == 0 else (err or f"exit {code}"),
            "stdout": out,
            "stderr": err,
            "exit_code": code,
            "action_id": action_id,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "action_id": action_id}


async def scale_service(
    server_id: str,
    compose_file: str,
    service_name: str,
    replicas: int,
    action_id: str,
    approved: bool = False,
) -> dict[str, Any]:
    command = f"up -d --scale {shlex.quote(service_name)}={int(replicas)}"
    result = await run_compose_command(
        server_id,
        compose_file,
        command,
        action_id,
        approved=approved,
        service_name=service_name,
    )
    if result.get("success"):
        result["previous_replicas"] = None
        result["new_replicas"] = replicas
    return result


async def rollback_deployment(
    server_id: str,
    service_name: str,
    compose_file: str,
    action_id: str,
    approved: bool = False,
) -> dict[str, Any]:
    try:
        server = _get_server(server_id)
        blocked = await _guard_execution(
            server, service_name=service_name, approved=approved
        )
        if blocked:
            blocked["action_id"] = action_id
            return blocked

        from db import store

        container_hint = service_name.replace(" ", "-").lower()
        previous_image = await store.get_last_healthy_image(server_id, container_hint)
        if not previous_image:
            for c in (await store.get_latest_snapshot(server_id) or {}).get(
                "container_statuses"
            ) or []:
                if service_name.lower() in (c.get("name") or "").lower():
                    container_hint = c.get("name", container_hint)
                    previous_image = await store.get_last_healthy_image(
                        server_id, container_hint
                    )
                    break
        if not previous_image:
            return {
                "success": False,
                "error": "No healthy snapshot image found for rollback",
                "action_id": action_id,
            }

        compose = get_compose_command(server_id) or await detect_compose_command(server)
        safe_image = previous_image.replace("'", "'\\''")
        safe_file = compose_file.replace("'", "'\\''")
        safe_svc = service_name.replace("'", "'\\''")
        patch_cmd = (
            f"cp '{safe_file}' '{safe_file}.bak.{action_id}' && "
            f"awk -v svc='{safe_svc}' -v img='{safe_image}' '"
            "/^[[:space:]]+[a-zA-Z0-9_.-]+:/ { in_block=($0 ~ \"^[[:space:]]+\" svc \":\") } "
            "in_block && /^[[:space:]]+image:/ { "
            "sub(/image:.*/, \"image: \" img); in_block=0 } { print }' "
            f"'{safe_file}' > '{safe_file}.tmp' && mv '{safe_file}.tmp' '{safe_file}'"
        )
        up_cmd = f"{compose} -f '{safe_file}' up -d '{safe_svc}'"
        await _log_line(action_id, f"$ # rollback to image {previous_image}\n")
        await _log_line(action_id, f"$ {patch_cmd}\n")
        code, out, err = await run_ssh(server, patch_cmd)
        output = (out or "") + (err or "")
        await _log_line(action_id, output or f"patch exit {code}\n")
        if code != 0:
            return {
                "success": False,
                "error": err or f"compose patch failed exit {code}",
                "output": output,
                "action_id": action_id,
            }
        await _log_line(action_id, f"$ {up_cmd}\n")
        code2, out2, err2 = await run_ssh(server, up_cmd)
        output2 = (out2 or "") + (err2 or "")
        await _log_line(action_id, output2 or f"up exit {code2}\n")
        if code2 != 0:
            return {
                "success": False,
                "error": err2 or f"compose up failed exit {code2}",
                "output": output + output2,
                "action_id": action_id,
            }
        return {
            "success": True,
            "error": None,
            "output": output + output2,
            "previous_image": previous_image,
            "current_image": previous_image,
            "action_id": action_id,
        }
    except Exception as exc:
        logger.warning("rollback_deployment failed: %s", exc)
        return {"success": False, "error": str(exc), "action_id": action_id}


async def snapshot_container_states(server_id: str) -> dict[str, Any]:
    """Pre-execution snapshot helper."""
    snap = await collect_health_snapshot(_get_server(server_id))
    return snap if snap else {"success": False, "error": "server not found"}
