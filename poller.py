"""Background health poller — SSH every 30s, snapshots, WebSocket updates."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from agent import run_agent_loop
from db import store
from health_metrics import (
    build_server_health,
    count_restart_events,
    derive_server_status,
)
from models.config import ServerConfig, load_app_config
from models.incident import AnomalyEvent
from ssh_client import detect_compose_command, is_server_reachable
from tools.infrastructure import collect_health_snapshot
from ws_hub import ws_broadcast

logger = logging.getLogger(__name__)

_poller_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None
_consecutive_critical: dict[str, int] = {}
_last_container_statuses: dict[str, list[dict]] = {}
_baseline_refresh_counter = 0
_last_anomaly_signature: dict[str, str] = {}


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _is_anomaly(
    server: ServerConfig,
    cpu: float | None,
    mem: float | None,
    disk: float | None,
    restart_events: int,
) -> tuple[bool, str]:
    t = server.thresholds
    reasons = []
    if cpu is not None and cpu > t.cpu_percent:
        reasons.append(f"CPU {cpu}% > {t.cpu_percent}%")
    if mem is not None and mem > t.memory_percent:
        reasons.append(f"Memory {mem}% > {t.memory_percent}%")
    if disk is not None and disk > t.disk_percent:
        reasons.append(f"Disk {disk}% > {t.disk_percent}%")
    if restart_events >= t.container_restart_count:
        reasons.append(f"Container restarts ({restart_events}) in window")
    if reasons:
        return True, "; ".join(reasons)
    return False, ""


def _match_service(server: ServerConfig, container_name: str) -> str | None:
    name_lower = container_name.lower()
    for svc in server.services:
        if svc.name.lower() in name_lower or name_lower in svc.name.lower():
            return svc.name
    return None


def _container_anomaly(
    server: ServerConfig, containers: list[dict]
) -> tuple[bool, str, str | None]:
    for c in containers:
        status = (c.get("status") or "").lower()
        if "exited" in status or "restarting" in status or "dead" in status:
            name = c.get("name", "unknown")
            svc = _match_service(server, name)
            return True, f"Container {name} unhealthy: {c.get('status')}", svc
    return False, "", None


def _trigger_agent(
    server: ServerConfig, reason: str, service_name: str | None, metrics: dict
) -> None:
    signature = f"{reason}|{service_name or ''}"
    if _last_anomaly_signature.get(server.id) == signature:
        return
    _last_anomaly_signature[server.id] = signature
    asyncio.create_task(
        run_agent_loop(
            AnomalyEvent(
                server_id=server.id,
                service_name=service_name,
                reason=reason,
                severity="high" if service_name else "medium",
                metrics=metrics,
            )
        ),
        name=f"agent-{server.id}",
    )


async def _poll_server(server: ServerConfig) -> None:
    if not is_server_reachable(server):
        logger.debug("Skipping unconfigured server %s", server.id)
        return

    try:
        await detect_compose_command(server)
        snap = await collect_health_snapshot(server)
        if not snap.get("success"):
            logger.error("Poll failed %s: %s", server.id, snap.get("error"))
            await store.upsert_server(
                server.id, server.label, server.host, status="unknown"
            )
            await ws_broadcast(
                {
                    "type": "snapshot_update",
                    "server_id": server.id,
                    "data": {
                        "server_id": server.id,
                        "label": server.label,
                        "status": "unknown",
                        "error": snap.get("error"),
                    },
                }
            )
            return

        containers = snap.get("containers") or []
        prev = _last_container_statuses.get(server.id)
        restart_events = count_restart_events(containers, prev)
        _last_container_statuses[server.id] = containers

        cpu = snap.get("cpu_percent")
        mem = snap.get("memory_percent")
        disk = snap.get("disk_percent")

        crit_key = server.id
        if (cpu and cpu > server.thresholds.cpu_percent) or (
            mem and mem > server.thresholds.memory_percent
        ):
            _consecutive_critical[crit_key] = _consecutive_critical.get(crit_key, 0) + 1
        else:
            _consecutive_critical[crit_key] = 0

        from health_metrics import ContainerStatus

        container_objs = [
            ContainerStatus(
                name=c["name"],
                status=c["status"],
                image=c.get("image", ""),
                restart_count=c.get("restart_count", 0),
            )
            for c in containers
        ]
        status = derive_server_status(
            metrics={"cpu_percent": cpu, "memory_percent": mem, "disk_percent": disk},
            containers=container_objs,
            thresholds=server.thresholds,
            consecutive_critical=_consecutive_critical.get(crit_key, 0),
        )

        captured_at = _utc_now_iso()
        await store.insert_snapshot(
            server.id,
            cpu_percent=cpu,
            memory_percent=mem,
            disk_percent=disk,
            container_statuses=containers,
            raw_data={"docker_running": snap.get("docker_running")},
        )
        await store.upsert_server(
            server.id,
            server.label,
            server.host,
            last_seen_at=captured_at,
            status=status,
        )

        health = build_server_health(
            server.id,
            server.label,
            status,
            cpu,
            mem,
            disk,
            container_objs,
            captured_at,
        )
        await ws_broadcast(
            {
                "type": "snapshot_update",
                "server_id": server.id,
                "data": health.to_ws_payload(),
            }
        )

        metrics = {
            "cpu_percent": cpu,
            "memory_percent": mem,
            "disk_percent": disk,
            "restart_events": restart_events,
        }
        is_bad, reason = _is_anomaly(server, cpu, mem, disk, restart_events)
        svc_from_container: str | None = None
        if not is_bad:
            is_bad, reason, svc_from_container = _container_anomaly(server, containers)

        if is_bad:
            logger.warning("Anomaly detected on %s: %s", server.id, reason)
            _trigger_agent(server, reason, svc_from_container, metrics)
        else:
            _last_anomaly_signature.pop(server.id, None)

    except Exception as exc:
        err_msg = str(exc).split("\n")[0][:200]
        logger.error("Poller error for %s: %s", server.id, err_msg)
        await store.upsert_server(server.id, server.label, server.host, status="unknown")
        await ws_broadcast(
            {
                "type": "snapshot_update",
                "server_id": server.id,
                "data": {
                    "server_id": server.id,
                    "label": server.label,
                    "status": "unknown",
                    "error": err_msg,
                },
            }
        )


async def _maybe_refresh_baselines() -> None:
    global _baseline_refresh_counter
    _baseline_refresh_counter += 1
    if _baseline_refresh_counter % 720 != 0:  # ~6h at 30s interval
        return
    try:
        cfg = load_app_config()
        for server in cfg.servers.servers:
            if not is_server_reachable(server):
                continue
            cpu_p95, mem_p95 = await store.compute_baseline_p95(server.id, hours=24)
            await store.upsert_baseline(server.id, cpu_p95, mem_p95)
    except FileNotFoundError:
        pass


async def run_poller_loop() -> None:
    global _stop_event
    _stop_event = asyncio.Event()
    logger.info("Poller started")
    interval = 30
    while not _stop_event.is_set():
        try:
            cfg = load_app_config()
            interval = cfg.rules.automation.poll_interval_seconds
            await asyncio.gather(
                *[_poll_server(s) for s in cfg.servers.servers],
                return_exceptions=True,
            )
            await _maybe_refresh_baselines()
        except FileNotFoundError as exc:
            logger.warning("Poller: %s", exc)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Poller loop error")

        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=interval)
            break
        except TimeoutError:
            pass
        except FileNotFoundError:
            await asyncio.sleep(30)


async def start_poller() -> None:
    global _poller_task
    if _poller_task is not None and not _poller_task.done():
        return
    _poller_task = asyncio.create_task(run_poller_loop(), name="health-poller")
    logger.info("Poller task scheduled")


async def stop_poller() -> None:
    global _poller_task, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    if _poller_task is not None:
        _poller_task.cancel()
        try:
            await asyncio.wait_for(_poller_task, timeout=15.0)
        except (asyncio.CancelledError, TimeoutError):
            pass
        _poller_task = None
    _stop_event = None
    logger.info("Poller stopped")
