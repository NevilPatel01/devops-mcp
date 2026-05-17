"""Infrastructure tools tests — mock SSH, no real VPS."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from health_metrics import parse_cpu_percent, parse_disk_percent, parse_memory_percent
from models.config import ServerConfig, ThresholdConfig
from tools import infrastructure


def test_parse_cpu_percent() -> None:
    line = "cpu  3357 12 1824 432423 890 0 203 0 0 0"
    assert parse_cpu_percent(line) is not None


def test_parse_memory_percent() -> None:
    out = "Mem:          7951        2048        5000\n"
    assert parse_memory_percent(out) == pytest.approx(25.8, rel=0.1)


def test_parse_disk_percent() -> None:
    out = (
        "Filesystem      Size  Used Avail Use% Mounted on\n"
        "/dev/sda1        50G   20G   28G  42% /\n"
    )
    assert parse_disk_percent(out) == 42.0


@pytest.mark.asyncio
async def test_get_server_health_unknown_id() -> None:
    with patch("tools.infrastructure.load_servers_config") as mock_cfg:
        mock_cfg.return_value.servers = []  # ServersFile.servers
        result = await infrastructure.get_server_health("missing")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_collect_health_snapshot_mock() -> None:
    server = ServerConfig(
        id="test",
        label="Test",
        host="127.0.0.1",
        thresholds=ThresholdConfig(),
    )

    combined = "\n".join(
        [
            "cpu  100 0 50 850 0 0 0 0 0 0",
            "Mem:          1000         500         500",
            "/dev/x 10G 5G 5G 50% /",
            "active",
            '{"Names":"web","Status":"Up 1 hour","Image":"nginx:latest"}',
        ]
    )

    with patch("tools.infrastructure.run_ssh_script", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (0, combined, "")
        snap = await infrastructure.collect_health_snapshot(server)

    assert snap["success"] is True
    assert snap["docker_running"] is True
    assert len(snap["containers"]) == 1
