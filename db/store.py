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
    return _snapshot_row_to_dict(row)


def _snapshot_row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    data = dict(row)
    data["container_statuses"] = json.loads(data.get("container_statuses") or "[]")
    raw = data.get("raw_data")
    if isinstance(raw, str):
        data["raw_data"] = json.loads(raw or "{}")
    return data


async def get_recent_snapshots(server_id: str, limit: int = 5) -> list[dict[str, Any]]:
    conn = await _conn()
    cursor = await conn.execute(
        """
        SELECT * FROM snapshots WHERE server_id = ?
        ORDER BY captured_at DESC LIMIT ?
        """,
        (server_id, limit),
    )
    rows = await cursor.fetchall()
    return [_snapshot_row_to_dict(r) for r in rows]


async def create_incident(
    incident_id: str,
    server_id: str,
    title: str,
    description: str,
    severity: str,
    service_name: str | None = None,
) -> dict[str, Any]:
    conn = await _conn()
    await conn.execute(
        """
        INSERT INTO incidents (id, server_id, service_name, title, description, severity)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (incident_id, server_id, service_name, title, description, severity),
    )
    await conn.commit()
    row = await get_incident(incident_id)
    assert row is not None
    return row


async def get_incident(incident_id: str) -> dict[str, Any] | None:
    conn = await _conn()
    cursor = await conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def list_incidents(limit: int = 50) -> list[dict[str, Any]]:
    conn = await _conn()
    cursor = await conn.execute(
        """
        SELECT * FROM incidents ORDER BY created_at DESC LIMIT ?
        """,
        (limit,),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def update_incident_status(
    incident_id: str,
    status: str,
    *,
    root_cause: str | None = None,
    resolved_at: str | None = None,
) -> None:
    conn = await _conn()
    await conn.execute(
        """
        UPDATE incidents
        SET status = ?, root_cause = COALESCE(?, root_cause),
            resolved_at = COALESCE(?, resolved_at)
        WHERE id = ?
        """,
        (status, root_cause, resolved_at, incident_id),
    )
    await conn.commit()


async def find_similar_incidents(
    server_id: str,
    service_name: str | None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    conn = await _conn()
    if service_name:
        cursor = await conn.execute(
            """
            SELECT * FROM incidents
            WHERE server_id = ? AND service_name = ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (server_id, service_name, limit),
        )
    else:
        cursor = await conn.execute(
            """
            SELECT * FROM incidents WHERE server_id = ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (server_id, limit),
        )
    return [dict(r) for r in await cursor.fetchall()]


def _action_row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    data = dict(row)
    params = data.get("parameters")
    if isinstance(params, str):
        data["parameters"] = json.loads(params or "{}")
    return data


async def insert_proposed_action(
    action_id: str,
    *,
    incident_id: str | None,
    action_type: str,
    description: str,
    rationale: str,
    risk_tier: str,
    rollback_plan: str,
    parameters: dict[str, Any],
    stale_after_hours: int = 24,
) -> dict[str, Any]:
    conn = await _conn()
    await conn.execute(
        """
        INSERT INTO proposed_actions (
            id, incident_id, action_type, description, rationale, risk_tier,
            rollback_plan, parameters, stale_after_hours
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            action_id,
            incident_id,
            action_type,
            description,
            rationale,
            risk_tier,
            rollback_plan,
            json.dumps(parameters),
            stale_after_hours,
        ),
    )
    await conn.commit()
    row = await get_proposed_action(action_id)
    assert row is not None
    return row


async def get_proposed_action(action_id: str) -> dict[str, Any] | None:
    conn = await _conn()
    cursor = await conn.execute(
        "SELECT * FROM proposed_actions WHERE id = ?", (action_id,)
    )
    row = await cursor.fetchone()
    return _action_row_to_dict(row) if row else None


async def get_pending_action_for_server(server_id: str) -> dict[str, Any] | None:
    conn = await _conn()
    cursor = await conn.execute(
        """
        SELECT * FROM proposed_actions
        WHERE status = 'pending'
          AND json_extract(parameters, '$.server_id') = ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (server_id,),
    )
    row = await cursor.fetchone()
    return _action_row_to_dict(row) if row else None


async def list_pending_actions() -> list[dict[str, Any]]:
    conn = await _conn()
    cursor = await conn.execute(
        """
        SELECT * FROM proposed_actions WHERE status = 'pending'
        ORDER BY created_at ASC
        """
    )
    return [_action_row_to_dict(r) for r in await cursor.fetchall()]


async def update_action_status(
    action_id: str,
    status: str,
    *,
    reviewer_feedback: str | None = None,
) -> dict[str, Any] | None:
    conn = await _conn()
    await conn.execute(
        """
        UPDATE proposed_actions
        SET status = ?, reviewed_at = CURRENT_TIMESTAMP,
            reviewer_feedback = COALESCE(?, reviewer_feedback)
        WHERE id = ?
        """,
        (status, reviewer_feedback, action_id),
    )
    await conn.commit()
    return await get_proposed_action(action_id)


async def insert_feedback_rule(
    action_type: str,
    rule: str,
    *,
    service_name: str | None = None,
    server_id: str | None = None,
    created_from_action_id: str | None = None,
) -> int:
    conn = await _conn()
    cursor = await conn.execute(
        """
        INSERT INTO feedback_rules (
            action_type, service_name, server_id, rule, created_from_action_id
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (action_type, service_name, server_id, rule, created_from_action_id),
    )
    await conn.commit()
    return cursor.lastrowid or 0


async def list_feedback_rules(
    *,
    server_id: str | None = None,
    service_name: str | None = None,
) -> list[dict[str, Any]]:
    conn = await _conn()
    query = "SELECT * FROM feedback_rules WHERE 1=1"
    params: list[Any] = []
    if server_id:
        query += " AND (server_id IS NULL OR server_id = ?)"
        params.append(server_id)
    if service_name:
        query += " AND (service_name IS NULL OR service_name = ?)"
        params.append(service_name)
    query += " ORDER BY created_at DESC"
    cursor = await conn.execute(query, params)
    return [dict(r) for r in await cursor.fetchall()]


async def insert_action_log(
    action_id: str,
    output: str,
    success: bool,
) -> None:
    conn = await _conn()
    await conn.execute(
        """
        INSERT INTO action_logs (action_id, output, success) VALUES (?, ?, ?)
        """,
        (action_id, output, success),
    )
    await conn.commit()


async def get_actions_for_incident(incident_id: str) -> list[dict[str, Any]]:
    conn = await _conn()
    cursor = await conn.execute(
        """
        SELECT * FROM proposed_actions WHERE incident_id = ?
        ORDER BY created_at ASC
        """,
        (incident_id,),
    )
    return [_action_row_to_dict(r) for r in await cursor.fetchall()]


async def get_action_logs(action_id: str) -> list[dict[str, Any]]:
    conn = await _conn()
    cursor = await conn.execute(
        """
        SELECT * FROM action_logs WHERE action_id = ? ORDER BY timestamp ASC
        """,
        (action_id,),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def update_incident_postmortem(incident_id: str, postmortem: str) -> None:
    conn = await _conn()
    await conn.execute(
        "UPDATE incidents SET postmortem_draft = ? WHERE id = ?",
        (postmortem, incident_id),
    )
    await conn.commit()


async def mark_incident_false_positive(incident_id: str) -> dict[str, Any] | None:
    conn = await _conn()
    await conn.execute(
        """
        UPDATE incidents SET status = 'false_positive', resolved_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (incident_id,),
    )
    await conn.commit()
    return await get_incident(incident_id)


async def get_runbook(
    service_name: str, incident_type: str
) -> dict[str, Any] | None:
    conn = await _conn()
    cursor = await conn.execute(
        """
        SELECT * FROM runbooks
        WHERE service_name = ? AND incident_type = ?
        ORDER BY updated_at DESC LIMIT 1
        """,
        (service_name, incident_type),
    )
    row = await cursor.fetchone()
    if not row:
        return None
    data = dict(row)
    steps = data.get("steps")
    if isinstance(steps, str):
        data["steps"] = json.loads(steps or "[]")
    return data


async def list_recent_actions(hours: int = 8, limit: int = 50) -> list[dict[str, Any]]:
    conn = await _conn()
    cursor = await conn.execute(
        """
        SELECT * FROM proposed_actions
        WHERE created_at >= datetime('now', ?)
        ORDER BY created_at DESC LIMIT ?
        """,
        (f"-{hours} hours", limit),
    )
    return [_action_row_to_dict(r) for r in await cursor.fetchall()]


async def list_open_incidents() -> list[dict[str, Any]]:
    conn = await _conn()
    cursor = await conn.execute(
        """
        SELECT * FROM incidents
        WHERE status IN ('open', 'investigating')
        ORDER BY created_at DESC
        """
    )
    return [dict(r) for r in await cursor.fetchall()]


async def get_snapshot_history(
    server_id: str, limit: int = 48
) -> list[dict[str, Any]]:
    return await get_recent_snapshots(server_id, limit=limit)


async def get_last_healthy_image(
    server_id: str, container_name: str, *, lookback: int = 200
) -> str | None:
    """Previous image from last healthy snapshot (Phase 4 rollback)."""
    snaps = await get_recent_snapshots(server_id, limit=lookback)
    name_lower = container_name.lower()
    for snap in snaps:
        for c in snap.get("container_statuses") or []:
            cname = (c.get("name") or "").lower()
            status = (c.get("status") or "").lower()
            if (cname == name_lower or name_lower in cname) and "up" in status:
                if "exited" not in status and "restarting" not in status:
                    image = c.get("image")
                    if image:
                        return image
    return None


async def get_snapshots_for_incident_window(
    server_id: str, minutes: int = 30, limit: int = 50
) -> list[dict[str, Any]]:
    conn = await _conn()
    cursor = await conn.execute(
        """
        SELECT * FROM snapshots
        WHERE server_id = ? AND captured_at >= datetime('now', ?)
        ORDER BY captured_at DESC LIMIT ?
        """,
        (server_id, f"-{minutes} minutes", limit),
    )
    return [_snapshot_row_to_dict(r) for r in await cursor.fetchall()]
