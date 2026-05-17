"""Read-only SSH / Docker MCP tools."""

from __future__ import annotations

import json
import logging
from typing import Any

from health_metrics import (
    parse_cpu_percent,
    parse_disk_percent,
    parse_docker_ps_json,
    parse_memory_percent,
)
from models.config import ServerConfig, load_servers_config
from ssh_client import detect_compose_command, is_server_reachable, run_ssh, run_ssh_script

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


async def _tool_error(server_id: str, exc: Exception) -> dict[str, Any]:
    logger.warning("Tool error server=%s: %s", server_id, exc)
    return {"success": False, "error": str(exc), "server_id": server_id}


async def collect_health_snapshot(server: ServerConfig) -> dict[str, Any]:
    """Collect metrics used by poller and get_server_health."""
    if not is_server_reachable(server):
        return {"success": False, "error": f"Server {server.id} is not configured"}

    code, combined, err = await run_ssh_script(
        server,
        [
            "grep '^cpu ' /proc/stat | head -1",
            "free -m | grep '^Mem:'",
            "df -h / | tail -1",
            "systemctl is-active docker 2>/dev/null || true",
            "docker ps -a --format '{{json .}}'",
        ],
    )
    lines = combined.splitlines()
    proc_out = lines[0] if lines else ""
    free_out = lines[1] if len(lines) > 1 else ""
    df_out = lines[2] if len(lines) > 2 else ""
    docker_svc = lines[3] if len(lines) > 3 else ""
    ps_out = "\n".join(lines[4:]) if len(lines) > 4 else ""

    if code != 0 and not ps_out.strip():
        return {"success": False, "error": err.strip() or f"docker ps failed exit {code}"}

    cpu = parse_cpu_percent(proc_out)
    memory = parse_memory_percent(free_out)
    disk = parse_disk_percent(df_out)
    docker_running = docker_svc.strip() == "active"
    containers = parse_docker_ps_json(ps_out)

    return {
        "success": True,
        "error": None,
        "cpu_percent": cpu,
        "memory_percent": memory,
        "disk_percent": disk,
        "docker_running": docker_running,
        "containers": [
            {
                "name": c.name,
                "status": c.status,
                "image": c.image,
                "restart_count": c.restart_count,
            }
            for c in containers
        ],
    }


async def get_server_health(server_id: str) -> dict[str, Any]:
    try:
        server = _get_server(server_id)
        if not server:
            return {"success": False, "error": f"Unknown server_id: {server_id}"}
        snap = await collect_health_snapshot(server)
        if not snap.get("success"):
            return snap
        return {
            "success": True,
            "error": None,
            "cpu_percent": snap["cpu_percent"],
            "memory_percent": snap["memory_percent"],
            "disk_percent": snap["disk_percent"],
            "load_average": None,
            "uptime_seconds": None,
            "docker_running": snap["docker_running"],
        }
    except Exception as exc:
        return await _tool_error(server_id, exc)


async def list_containers(server_id: str) -> dict[str, Any]:
    try:
        server = _get_server(server_id)
        if not server:
            return {"success": False, "error": f"Unknown server_id: {server_id}"}
        code, out, err = await run_ssh(
            server, "docker ps -a --format '{{json .}}'"
        )
        if code != 0 and not out.strip():
            return {"success": False, "error": err or f"exit {code}"}
        containers = []
        for c in parse_docker_ps_json(out):
            containers.append(
                {
                    "name": c.name,
                    "status": c.status,
                    "image": c.image,
                    "restart_count": c.restart_count,
                    "created_at": c.created_at,
                    "ports": c.ports,
                }
            )
        return {"success": True, "error": None, "containers": containers}
    except Exception as exc:
        return await _tool_error(server_id, exc)


async def get_container_logs(
    server_id: str, container_name: str, tail: int = 100
) -> dict[str, Any]:
    try:
        server = _get_server(server_id)
        if not server:
            return {"success": False, "error": f"Unknown server_id: {server_id}"}
        safe_name = container_name.replace("'", "")
        cmd = f"docker logs --tail {int(tail)} --timestamps '{safe_name}' 2>&1"
        code, out, err = await run_ssh(server, cmd)
        logs = out if out else err
        return {
            "success": code == 0 or bool(logs),
            "error": None if code == 0 or logs else err,
            "logs": logs,
            "container_name": container_name,
            "server_id": server_id,
        }
    except Exception as exc:
        return await _tool_error(server_id, exc)


async def get_docker_compose_status(server_id: str, compose_file: str) -> dict[str, Any]:
    try:
        server = _get_server(server_id)
        if not server:
            return {"success": False, "error": f"Unknown server_id: {server_id}"}
        compose = await detect_compose_command(server)
        cmd = f"{compose} -f {compose_file} ps --format json 2>/dev/null"
        code, out, err = await run_ssh(server, cmd)
        services = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                services.append(
                    {
                        "name": obj.get("Name") or obj.get("Service"),
                        "state": obj.get("State") or obj.get("Status"),
                        "health": obj.get("Health"),
                    }
                )
            except json.JSONDecodeError:
                continue
        if not services and code != 0:
            return {"success": False, "error": err or out}
        return {"success": True, "error": None, "services": services}
    except Exception as exc:
        return await _tool_error(server_id, exc)


async def check_disk_usage(server_id: str) -> dict[str, Any]:
    try:
        server = _get_server(server_id)
        if not server:
            return {"success": False, "error": f"Unknown server_id: {server_id}"}
        code, out, err = await run_ssh(
            server, "df -h; du -sh /var/lib/docker 2>/dev/null"
        )
        if code != 0 and not out:
            return {"success": False, "error": err}
        filesystems = []
        docker_size_gb = 0.0
        for line in out.splitlines():
            if line.startswith("Filesystem"):
                continue
            parts = line.split()
            if line.startswith("/") or (len(parts) >= 6 and parts[-1].startswith("/")):
                if len(parts) >= 5:
                    mount = parts[-1]
                    used_pct = parts[-2].rstrip("%")
                    avail = parts[-3]
                    try:
                        filesystems.append(
                            {
                                "mount": mount,
                                "used_percent": float(used_pct),
                                "available": avail,
                            }
                        )
                    except ValueError:
                        pass
            if "/var/lib/docker" in line:
                size = parts[0] if parts else ""
                if size.endswith("G"):
                    try:
                        docker_size_gb = float(size[:-1])
                    except ValueError:
                        pass
        return {
            "success": True,
            "error": None,
            "filesystems": filesystems,
            "docker_size_gb": docker_size_gb,
        }
    except Exception as exc:
        return await _tool_error(server_id, exc)


async def get_recent_events(server_id: str, minutes: int = 30) -> dict[str, Any]:
    try:
        server = _get_server(server_id)
        if not server:
            return {"success": False, "error": f"Unknown server_id: {server_id}"}
        cmd = (
            f'journalctl --since "{int(minutes)} minutes ago" '
            '--priority=err --no-pager -o short-iso 2>&1'
        )
        code, out, err = await run_ssh(server, cmd)
        if code != 0 and "permission denied" in (out + err).lower():
            cmd = (
                f'sudo journalctl --since "{int(minutes)} minutes ago" '
                '--priority=err --no-pager -o short-iso 2>&1'
            )
            code, out, err = await run_ssh(server, cmd)
        if code != 0 and "permission denied" in (out + err).lower():
            return {
                "success": True,
                "error": None,
                "events": [],
                "warning": "journalctl requires sudo — skipping",
            }
        events = []
        for line in out.splitlines():
            if not line.strip() or line.startswith("--"):
                continue
            events.append({"timestamp": line[:19], "unit": "", "message": line[20:]})
        return {"success": True, "error": None, "events": events}
    except Exception as exc:
        return await _tool_error(server_id, exc)
