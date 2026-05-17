"""SSH helpers — paramiko in thread pool, 10s timeout, no persistent pool leaks."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from pathlib import Path
from typing import TYPE_CHECKING

import paramiko
from paramiko import Ed25519Key, RSAKey

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


def _load_private_key(key_path: str) -> paramiko.PKey:
    """Load Ed25519 or RSA private key explicitly (more reliable than key_filename)."""
    path = Path(key_path)
    if not path.is_file():
        raise FileNotFoundError(f"SSH key not found: {key_path}")

    errors: list[str] = []
    for loader in (Ed25519Key.from_private_key_file, RSAKey.from_private_key_file):
        try:
            return loader(str(path))
        except Exception as exc:
            errors.append(str(exc))

    raise paramiko.SSHException(
        f"Could not load SSH key {key_path}: {'; '.join(errors)}"
    )


def _run_ssh_sync(server: ServerConfig, command: str, timeout: float) -> tuple[int, str, str]:
    key_path = expand_key_path(server.ssh_key_path)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        pkey = _load_private_key(key_path)
        client.connect(
            hostname=server.host,
            port=server.port,
            username=server.user,
            pkey=pkey,
            timeout=timeout,
            banner_timeout=timeout,
            auth_timeout=timeout,
            allow_agent=True,
            look_for_keys=False,
        )
        _, stdout, stderr = client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return exit_code, out, err
    except paramiko.AuthenticationException as exc:
        raise paramiko.AuthenticationException(
            f"SSH auth failed for {server.user}@{server.host} with key {key_path}. "
            f"Verify user and authorized_keys on the server."
        ) from exc
    finally:
        client.close()


async def run_ssh(
    server: ServerConfig,
    command: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[int, str, str]:
    return await asyncio.to_thread(_run_ssh_sync, server, command, timeout)


async def run_ssh_script(
    server: ServerConfig,
    commands: list[str],
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[int, str, str]:
    """Run multiple commands in one SSH session (separator: newline)."""
    script = "\n".join(commands)
    return await run_ssh(server, script, timeout=timeout)


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


def check_port_available(host: str, port: int) -> None:
    """Fail fast with a clear message if the dashboard port is taken."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
    except OSError as exc:
        hint = (
            f"Port {host}:{port} is already in use. "
            f"Stop the other process: lsof -i :{port}  "
            f"or set DASHBOARD_PORT in .env (e.g. 8081)."
        )
        raise OSError(hint) from exc
    finally:
        sock.close()
