"""SSH helpers — paramiko in thread pool, 10s timeout, no persistent pool leaks."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

import paramiko

if TYPE_CHECKING:
    from models.config import ServerConfig

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10.0
_compose_command: dict[str, str] = {}


def expand_key_path(path: str | None) -> str:
    raw = path or os.getenv("DEFAULT_SSH_KEY_PATH", "~/.ssh/id_ed25519")
    return os.path.expanduser(raw)


def is_server_reachable(server: ServerConfig) -> bool:
    host = (server.host or "").strip()
    if not host or host.startswith("YOUR_"):
        return False
    return True


def _run_ssh_sync(server: ServerConfig, command: str, timeout: float) -> tuple[int, str, str]:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=server.host,
            port=server.port,
            username=server.user,
            key_filename=expand_key_path(server.ssh_key_path),
            timeout=timeout,
            banner_timeout=timeout,
            auth_timeout=timeout,
        )
        _, stdout, stderr = client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return exit_code, out, err
    finally:
        client.close()


async def run_ssh(
    server: ServerConfig,
    command: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[int, str, str]:
    return await asyncio.to_thread(_run_ssh_sync, server, command, timeout)


async def detect_compose_command(server: ServerConfig) -> str:
    if server.id in _compose_command:
        return _compose_command[server.id]
    code, out, _ = await run_ssh(server, "docker compose version 2>/dev/null")
    cmd = "docker compose" if code == 0 and out.strip() else "docker-compose"
    _compose_command[server.id] = cmd
    logger.info("Server %s compose CLI: %s", server.id, cmd)
    return cmd


def get_compose_command(server_id: str) -> str | None:
    return _compose_command.get(server_id)
