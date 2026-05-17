"""Async SQLite access — all database I/O goes through this module."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiosqlite

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"
_db_path: Path | None = None
_connection: aiosqlite.Connection | None = None


def get_db_path() -> Path:
    global _db_path
    if _db_path is None:
        import os

        _db_path = Path(os.getenv("DATABASE_PATH", "./devops_agent.db"))
    return _db_path


async def init_db(db_path: Path | None = None) -> None:
    """Create database and apply schema."""
    global _connection, _db_path
    if db_path is not None:
        _db_path = db_path
    path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = _SCHEMA_PATH.read_text(encoding="utf-8")
    _connection = await aiosqlite.connect(path)
    _connection.row_factory = aiosqlite.Row
    await _connection.executescript(schema)
    await _connection.commit()


async def close_db() -> None:
    global _connection
    if _connection is not None:
        await _connection.close()
        _connection = None


async def _conn() -> aiosqlite.Connection:
    if _connection is None:
        await init_db()
    assert _connection is not None
    return _connection


async def upsert_server(
    server_id: str,
    label: str,
    host: str,
    *,
    last_seen_at: str | None = None,
    status: str = "unknown",
) -> None:
    conn = await _conn()
    await conn.execute(
        """
        INSERT INTO servers (id, label, host, last_seen_at, status)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            label = excluded.label,
            host = excluded.host,
            last_seen_at = COALESCE(excluded.last_seen_at, servers.last_seen_at),
            status = excluded.status
        """,
        (server_id, label, host, last_seen_at, status),
    )
    await conn.commit()


async def insert_snapshot(
    server_id: str,
    *,
    cpu_percent: float | None,
    memory_percent: float | None,
    disk_percent: float | None,
    container_statuses: list[dict[str, Any]] | None = None,
    raw_data: dict[str, Any] | None = None,
) -> int:
    conn = await _conn()
    cursor = await conn.execute(
        """
        INSERT INTO snapshots (
            server_id, cpu_percent, memory_percent, disk_percent,
            container_statuses, raw_data
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            server_id,
            cpu_percent,
            memory_percent,
            disk_percent,
            json.dumps(container_statuses or []),
            json.dumps(raw_data or {}),
        ),
    )
    await conn.commit()
    return cursor.lastrowid or 0


async def prune_snapshots_older_than_days(days: int = 7) -> int:
    conn = await _conn()
    cursor = await conn.execute(
        """
        DELETE FROM snapshots
        WHERE captured_at < datetime('now', ?)
        """,
        (f"-{days} days",),
    )
    await conn.commit()
    return cursor.rowcount or 0


async def get_server(server_id: str) -> dict[str, Any] | None:
    conn = await _conn()
    cursor = await conn.execute("SELECT * FROM servers WHERE id = ?", (server_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def list_servers() -> list[dict[str, Any]]:
    conn = await _conn()
    cursor = await conn.execute("SELECT * FROM servers ORDER BY id")
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def upsert_baseline(
    server_id: str,
    cpu_p95: float | None,
    memory_p95: float | None,
) -> None:
    conn = await _conn()
    await conn.execute(
        """
        INSERT INTO baselines (server_id, cpu_p95, memory_p95, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(server_id) DO UPDATE SET
            cpu_p95 = excluded.cpu_p95,
            memory_p95 = excluded.memory_p95,
            updated_at = CURRENT_TIMESTAMP
        """,
        (server_id, cpu_p95, memory_p95),
    )
    await conn.commit()


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    sorted_v = sorted(values)
    k = (len(sorted_v) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_v) - 1)
    if f == c:
        return round(sorted_v[f], 2)
    return round(sorted_v[f] + (sorted_v[c] - sorted_v[f]) * (k - f), 2)


async def compute_baseline_p95(
    server_id: str, hours: int = 24
) -> tuple[float | None, float | None]:
    conn = await _conn()
    cursor = await conn.execute(
        """
        SELECT cpu_percent, memory_percent FROM snapshots
        WHERE server_id = ? AND captured_at >= datetime('now', ?)
        """,
        (server_id, f"-{hours} hours"),
    )
    rows = await cursor.fetchall()
    cpus = [r["cpu_percent"] for r in rows if r["cpu_percent"] is not None]
    mems = [r["memory_percent"] for r in rows if r["memory_percent"] is not None]
    return _percentile(cpus, 95), _percentile(mems, 95)


async def get_latest_snapshot(server_id: str) -> dict[str, Any] | None:
    conn = await _conn()
    cursor = await conn.execute(
        """
        SELECT * FROM snapshots WHERE server_id = ?
        ORDER BY captured_at DESC LIMIT 1
        """,
        (server_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return None
    data = dict(row)
    data["container_statuses"] = json.loads(data.get("container_statuses") or "[]")
    return data
