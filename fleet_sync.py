"""Sync managed_servers DB ↔ config/servers.yaml for poller compatibility."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import yaml

from db import store
from models.config import (
    ServerConfig,
    ServersFile,
    ServiceConfig,
    ThresholdConfig,
    load_servers_config,
)

logger = logging.getLogger(__name__)

_CONFIG_ROOT = Path(__file__).resolve().parent / "config"
_KEYS_DIR = Path(__file__).resolve().parent / "data" / "keys"


def servers_yaml_path() -> Path:
    return Path(os.getenv("SERVERS_CONFIG_PATH", _CONFIG_ROOT / "servers.yaml"))


def slugify(value: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", value.lower().strip())
    return s.strip("-")[:48] or "server"


def managed_row_to_server_config(row: dict) -> ServerConfig:
    thresholds_raw = row.get("thresholds") or {}
    services_raw = row.get("services") or []
    services = [
        ServiceConfig(
            name=s["name"],
            compose_file=s.get("compose_file", ""),
            sensitive=bool(s.get("sensitive", False)),
            health_check_url=s.get("health_check_url"),
        )
        for s in services_raw
        if s.get("name")
    ]
    return ServerConfig(
        id=row["id"],
        label=row["label"],
        host=row["host"],
        port=int(row.get("port") or 22),
        user=row.get("ssh_user") or "root",
        ssh_key_path=row.get("ssh_key_path") or "~/.ssh/id_ed25519",
        services=services,
        thresholds=ThresholdConfig.model_validate(
            thresholds_raw or ThresholdConfig().model_dump()
        ),
    )


async def import_yaml_to_db_if_empty() -> None:
    """One-time bootstrap: copy existing servers.yaml into managed_servers."""
    if await store.count_managed_servers() > 0:
        return
    path = servers_yaml_path()
    if not path.is_file():
        return
    try:
        cfg = load_servers_config(path)
    except Exception as exc:
        logger.warning("Could not import servers.yaml: %s", exc)
        return
    for srv in cfg.servers:
        await store.upsert_managed_server(
            srv.id,
            label=srv.label,
            host=srv.host,
            port=srv.port,
            ssh_user=srv.user,
            ssh_key_path=srv.ssh_key_path,
            services=[
                {
                    "name": s.name,
                    "compose_file": s.compose_file,
                    "sensitive": s.sensitive,
                    "health_check_url": s.health_check_url,
                }
                for s in srv.services
            ],
            thresholds=srv.thresholds.model_dump(),
        )
    logger.info("Imported %d server(s) from servers.yaml into DB", len(cfg.servers))


async def rebuild_servers_yaml() -> None:
    """Write managed_servers back to servers.yaml for poller/tools."""
    rows = await store.list_managed_servers()
    if not rows:
        return

    protected: list[str] = ["primary DB"]
    path = servers_yaml_path()
    if path.is_file():
        try:
            existing = load_servers_config(path)
            protected = existing.protected_services or protected
        except Exception:
            pass

    servers_out = []
    for row in rows:
        srv = managed_row_to_server_config(row)
        servers_out.append(
            {
                "id": srv.id,
                "label": srv.label,
                "host": srv.host,
                "port": srv.port,
                "user": srv.user,
                "ssh_key_path": srv.ssh_key_path,
                "services": [
                    {
                        "name": s.name,
                        "compose_file": s.compose_file,
                        "sensitive": s.sensitive,
                        **(
                            {"health_check_url": s.health_check_url}
                            if s.health_check_url
                            else {}
                        ),
                    }
                    for s in srv.services
                ],
                "thresholds": srv.thresholds.model_dump(),
            }
        )

    doc = {"protected_services": protected, "servers": servers_out}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    logger.info("Wrote %d server(s) to %s", len(servers_out), path)


async def load_fleet_servers_file() -> ServersFile:
    """Prefer DB fleet; fall back to yaml."""
    await import_yaml_to_db_if_empty()
    rows = await store.list_managed_servers()
    if rows:
        servers = [managed_row_to_server_config(r) for r in rows]
        protected: list[str] = ["primary DB"]
        path = servers_yaml_path()
        if path.is_file():
            try:
                protected = load_servers_config(path).protected_services
            except Exception:
                pass
        return ServersFile(protected_services=protected, servers=servers)
    return load_servers_config()


def save_uploaded_key(server_id: str, key_pem: str) -> str:
    """Persist uploaded private key; return path."""
    _KEYS_DIR.mkdir(parents=True, exist_ok=True)
    path = _KEYS_DIR / f"{slugify(server_id)}.pem"
    path.write_text(key_pem.strip() + "\n", encoding="utf-8")
    path.chmod(0o600)
    return str(path)
