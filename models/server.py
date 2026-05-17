"""Server health dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContainerStatus:
    name: str
    status: str
    image: str = ""
    restart_count: int = 0
    created_at: str = ""
    ports: str = ""


@dataclass
class ServerHealth:
    server_id: str
    label: str
    status: str
    cpu_percent: float | None = None
    memory_percent: float | None = None
    disk_percent: float | None = None
    container_count: int = 0
    containers: list[ContainerStatus] = field(default_factory=list)
    captured_at: str | None = None

    def to_ws_payload(self) -> dict[str, Any]:
        return {
            "server_id": self.server_id,
            "label": self.label,
            "status": self.status,
            "cpu_percent": self.cpu_percent,
            "memory_percent": self.memory_percent,
            "disk_percent": self.disk_percent,
            "container_count": self.container_count,
            "containers": [
                {
                    "name": c.name,
                    "status": c.status,
                    "image": c.image,
                    "restart_count": c.restart_count,
                }
                for c in self.containers
            ],
            "captured_at": self.captured_at,
        }
