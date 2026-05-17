"""Parse SSH command output into health metrics."""

from __future__ import annotations

import json
from typing import Any

from models.server import ContainerStatus, ServerHealth


def parse_cpu_percent(proc_stat_line: str) -> float | None:
    parts = proc_stat_line.strip().split()
    if len(parts) < 5 or parts[0] != "cpu":
        return None
    try:
        user = float(parts[1])
        nice = float(parts[2])
        system = float(parts[3])
        idle = float(parts[4])
        total = user + nice + system + idle
        if total <= 0:
            return None
        return round((user + nice + system) * 100.0 / total, 1)
    except (ValueError, IndexError):
        return None


def parse_memory_percent(free_output: str) -> float | None:
    for line in free_output.splitlines():
        if line.startswith("Mem:"):
            parts = line.split()
            if len(parts) >= 3:
                try:
                    total = float(parts[1])
                    used = float(parts[2])
                    if total > 0:
                        return round(used * 100.0 / total, 1)
                except ValueError:
                    pass
    return None


def parse_disk_percent(df_output: str) -> float | None:
    for line in df_output.splitlines():
        if line.startswith("Filesystem"):
            continue
        parts = line.split()
        if len(parts) >= 5 and parts[-1] == "/":
            pct = parts[-2].rstrip("%")
            try:
                return float(pct)
            except ValueError:
                pass
    # fallback: first data row
    for line in df_output.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 5:
            pct = parts[-2].rstrip("%")
            try:
                return float(pct)
            except ValueError:
                continue
    return None


def parse_docker_ps_json(output: str) -> list[ContainerStatus]:
    containers: list[ContainerStatus] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        name = (obj.get("Names") or obj.get("Name") or "").lstrip("/")
        status = obj.get("Status") or obj.get("State") or "unknown"
        image = obj.get("Image") or ""
        restart_count = 0
        if "Restarting" in status or "Exited" in status:
            restart_count = 1
        containers.append(
            ContainerStatus(
                name=name,
                status=status,
                image=image,
                restart_count=restart_count,
            )
        )
    return containers


def derive_server_status(
    *,
    metrics: dict[str, float | None],
    containers: list[ContainerStatus],
    thresholds: Any,
    consecutive_critical: int,
) -> str:
    cpu = metrics.get("cpu_percent")
    mem = metrics.get("memory_percent")
    disk = metrics.get("disk_percent")

    down = sum(
        1
        for c in containers
        if any(x in (c.status or "").lower() for x in ("exited", "dead", "restarting"))
    )
    over_threshold = sum(
        1
        for v, limit in (
            (cpu, thresholds.cpu_percent),
            (mem, thresholds.memory_percent),
            (disk, thresholds.disk_percent),
        )
        if v is not None and v > limit
    )

    if down >= 2 or consecutive_critical >= 10 or over_threshold >= 2:
        return "critical"
    if down >= 1 or over_threshold >= 1:
        return "degraded"
    if cpu is not None or mem is not None:
        return "healthy"
    return "unknown"


def build_server_health(
    server_id: str,
    label: str,
    status: str,
    cpu: float | None,
    mem: float | None,
    disk: float | None,
    containers: list[ContainerStatus],
    captured_at: str,
) -> ServerHealth:
    return ServerHealth(
        server_id=server_id,
        label=label,
        status=status,
        cpu_percent=cpu,
        memory_percent=mem,
        disk_percent=disk,
        container_count=len(containers),
        containers=containers,
        captured_at=captured_at,
    )


def count_restart_events(
    current: list[dict[str, Any]],
    previous: list[dict[str, Any]] | None,
) -> int:
    if not previous:
        return 0
    prev_map = {c.get("name"): c.get("status") for c in previous}
    events = 0
    for c in current:
        name = c.get("name")
        if not name:
            continue
        cur_status = (c.get("status") or "").lower()
        prev_status = (prev_map.get(name) or "").lower()
        if "running" in prev_status and any(
            x in cur_status for x in ("restarting", "exited", "dead")
        ):
            events += 1
    return events
