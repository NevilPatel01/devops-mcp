"""SSH connection test and compose discovery for fleet onboarding."""

from __future__ import annotations

import logging
import re

from health_metrics import parse_docker_ps_json
from models.config import ServerConfig, ThresholdConfig
from ssh_client import run_ssh

logger = logging.getLogger(__name__)

_COMPOSE_FIND = (
    "find /home /var/www /opt /srv -maxdepth 4 "
    "-name 'docker-compose.yml' -o -name 'docker-compose.yaml' 2>/dev/null | head -20"
)


async def test_ssh_connection(
    *,
    host: str,
    port: int = 22,
    user: str = "root",
    ssh_key_path: str = "~/.ssh/id_ed25519",
) -> dict:
    server = ServerConfig(
        id="probe",
        label="probe",
        host=host,
        port=port,
        user=user,
        ssh_key_path=ssh_key_path,
        thresholds=ThresholdConfig(),
    )
    try:
        probe_cmd = "echo ok && docker ps --format '{{.Names}}' | head -5"
        code, out, err = await run_ssh(server, probe_cmd)
        if code != 0 or "ok" not in out:
            return {
                "success": False,
                "error": err.strip() or out.strip() or f"SSH failed (exit {code})",
            }
        containers = [ln.strip() for ln in out.splitlines() if ln.strip() and ln.strip() != "ok"]
        return {
            "success": True,
            "error": None,
            "message": f"Connected as {user}@{host}",
            "sample_containers": containers[:5],
        }
    except Exception as exc:
        logger.info("SSH test failed for %s@%s: %s", user, host, exc)
        return {"success": False, "error": str(exc)}


async def discover_compose_files(
    *,
    host: str,
    port: int = 22,
    user: str = "root",
    ssh_key_path: str = "~/.ssh/id_ed25519",
) -> dict:
    server = ServerConfig(
        id="probe",
        label="probe",
        host=host,
        port=port,
        user=user,
        ssh_key_path=ssh_key_path,
        thresholds=ThresholdConfig(),
    )
    try:
        code, out, err = await run_ssh(server, _COMPOSE_FIND, timeout=15.0)
        paths = [ln.strip() for ln in out.splitlines() if ln.strip()]
        return {
            "success": True,
            "error": None,
            "compose_files": paths,
            "stderr": err.strip() or None,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "compose_files": []}


async def list_remote_containers(server: ServerConfig) -> dict:
    try:
        code, out, err = await run_ssh(server, "docker ps -a --format '{{json .}}'")
        if code != 0:
            return {"success": False, "error": err.strip() or f"docker ps failed ({code})"}
        containers = parse_docker_ps_json(out)
        return {
            "success": True,
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
    except Exception as exc:
        return {"success": False, "error": str(exc), "containers": []}


def suggest_service_name(container_name: str, url: str | None) -> str:
    if url:
        host = re.sub(r"^https?://", "", url.strip()).split("/")[0]
        return host.replace(".", "-")[:32]
    return container_name[:32]
