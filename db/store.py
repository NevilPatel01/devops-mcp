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


async def _migrate_schema(conn: aiosqlite.Connection) -> None:
    """Apply additive migrations for existing databases."""
    cursor = await conn.execute("PRAGMA table_info(incidents)")
    incident_cols = {row[1] for row in await cursor.fetchall()}
    if "is_sensitive" not in incident_cols:
        await conn.execute(
            "ALTER TABLE incidents ADD COLUMN is_sensitive INTEGER DEFAULT 0"
        )
    cursor = await conn.execute("PRAGMA table_info(incidents)")
    incident_cols = {row[1] for row in await cursor.fetchall()}
    if "compliance_profile" not in incident_cols:
        await conn.execute("ALTER TABLE incidents ADD COLUMN compliance_profile TEXT")
    cursor = await conn.execute("PRAGMA table_info(incidents)")
    incident_cols = {row[1] for row in await cursor.fetchall()}
    if "incident_type" not in incident_cols:
        await conn.execute("ALTER TABLE incidents ADD COLUMN incident_type TEXT")

    cursor = await conn.execute("PRAGMA table_info(runbooks)")
    runbook_cols = {row[1] for row in await cursor.fetchall()}
    for col, typedef in (
        ("runbook_id", "TEXT"),
        ("status", "TEXT DEFAULT 'draft'"),
        ("source_incident_id", "TEXT"),
        ("approved_at", "TIMESTAMP"),
        ("approved_by", "TEXT"),
        ("incident_signature", "TEXT"),
    ):
        if col not in runbook_cols:
            await conn.execute(f"ALTER TABLE runbooks ADD COLUMN {col} {typedef}")
    await conn.execute(
        "UPDATE runbooks SET status = 'draft' WHERE status IS NULL OR status = ''"
    )
    await conn.execute(
        "UPDATE runbooks SET runbook_id = CAST(id AS TEXT) WHERE runbook_id IS NULL"
    )

    cursor = await conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='compliance_audit_log'"
    )
    if not await cursor.fetchone():
        await conn.executescript(
            """
            CREATE TABLE compliance_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                server_id TEXT,
                service_name TEXT,
                incident_id TEXT,
                action_id TEXT,
                event_type TEXT NOT NULL,
                actor TEXT,
                details_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_compliance_audit_incident
                ON compliance_audit_log (incident_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_compliance_audit_timestamp
                ON compliance_audit_log (timestamp);
            """
        )

    cursor = await conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='terraform_analyses'"
    )
    if not await cursor.fetchone():
        await conn.executescript(
            """
            CREATE TABLE terraform_analyses (
                id TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                plan_digest TEXT,
                resource_change_count INTEGER,
                overall_risk_score REAL,
                summary_json TEXT,
                summary_markdown TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_terraform_analyses_created
                ON terraform_analyses (created_at DESC);
            """
        )

    for table_sql in (
        """
        CREATE TABLE IF NOT EXISTS suppression_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id TEXT NOT NULL,
            service_name TEXT,
            pattern_type TEXT NOT NULL,
            pattern_json TEXT NOT NULL,
            created_from_incident_id TEXT,
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_suppression_server_expires
            ON suppression_patterns (server_id, expires_at);
        """,
        """
        CREATE TABLE IF NOT EXISTS service_alert_fatigue (
            server_id TEXT NOT NULL,
            service_name TEXT NOT NULL,
            false_positive_count INTEGER DEFAULT 0,
            true_positive_count INTEGER DEFAULT 0,
            fatigue_score REAL DEFAULT 0.0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (server_id, service_name)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS service_baselines (
            server_id TEXT NOT NULL,
            service_name TEXT NOT NULL,
            cpu_p95 REAL,
            memory_p95 REAL,
            restart_rate_p95 REAL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (server_id, service_name)
        );
        """,
    ):
        name = table_sql.split("EXISTS ")[1].split(" ")[0]
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        )
        if not await cursor.fetchone():
            await conn.executescript(table_sql)

    cursor = await conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='managed_servers'"
    )
    if not await cursor.fetchone():
        await conn.executescript(
            """
            CREATE TABLE managed_servers (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                host TEXT NOT NULL,
                port INTEGER DEFAULT 22,
                ssh_user TEXT DEFAULT 'root',
                ssh_key_path TEXT DEFAULT '~/.ssh/id_ed25519',
                services_json TEXT DEFAULT '[]',
                thresholds_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE sites (
                id TEXT PRIMARY KEY,
                client_name TEXT,
                name TEXT NOT NULL,
                url TEXT,
                server_id TEXT NOT NULL,
                compose_file TEXT,
                service_name TEXT,
                environment TEXT DEFAULT 'production',
                repo_id TEXT,
                sensitive INTEGER DEFAULT 0,
                uptime_status TEXT DEFAULT 'unknown',
                uptime_status_code INTEGER,
                uptime_latency_ms REAL,
                uptime_checked_at TIMESTAMP,
                ssl_expires_at TIMESTAMP,
                status TEXT DEFAULT 'unknown',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX idx_sites_server ON sites (server_id);
            CREATE INDEX idx_sites_status ON sites (status);
            CREATE TABLE app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )


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
    await _migrate_schema(_connection)
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


async def get_baseline(server_id: str) -> dict[str, Any] | None:
    conn = await _conn()
    cursor = await conn.execute(
        "SELECT * FROM baselines WHERE server_id = ?", (server_id,)
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


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
    *,
    is_sensitive: int = 0,
    compliance_profile: str | None = None,
) -> dict[str, Any]:
    conn = await _conn()
    await conn.execute(
        """
        INSERT INTO incidents (
            id, server_id, service_name, title, description, severity,
            is_sensitive, compliance_profile
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            incident_id,
            server_id,
            service_name,
            title,
            description,
            severity,
            is_sensitive,
            compliance_profile,
        ),
    )
    await conn.commit()
    row = await get_incident(incident_id)
    assert row is not None
    return row


async def insert_compliance_audit(
    event_type: str,
    *,
    server_id: str | None = None,
    service_name: str | None = None,
    incident_id: str | None = None,
    action_id: str | None = None,
    actor: str | None = None,
    details: dict[str, Any] | None = None,
) -> int:
    conn = await _conn()
    cursor = await conn.execute(
        """
        INSERT INTO compliance_audit_log (
            server_id, service_name, incident_id, action_id,
            event_type, actor, details_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            server_id,
            service_name,
            incident_id,
            action_id,
            event_type,
            actor,
            json.dumps(details or {}),
        ),
    )
    await conn.commit()
    return cursor.lastrowid or 0


async def list_compliance_audit(
    *,
    incident_id: str | None = None,
    hours: int = 24,
    limit: int = 200,
) -> list[dict[str, Any]]:
    conn = await _conn()
    query = """
        SELECT * FROM compliance_audit_log
        WHERE timestamp >= datetime('now', ?)
    """
    params: list[Any] = [f"-{hours} hours"]
    if incident_id:
        query += " AND incident_id = ?"
        params.append(incident_id)
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    cursor = await conn.execute(query, params)
    rows = []
    for row in await cursor.fetchall():
        data = dict(row)
        raw = data.get("details_json")
        if isinstance(raw, str):
            data["details"] = json.loads(raw or "{}")
        rows.append(data)
    return rows


async def prune_compliance_audit_older_than_days(days: int = 90) -> int:
    conn = await _conn()
    cursor = await conn.execute(
        """
        DELETE FROM compliance_audit_log
        WHERE timestamp < datetime('now', ?)
        """,
        (f"-{days} days",),
    )
    await conn.commit()
    return cursor.rowcount or 0


async def insert_terraform_analysis(
    *,
    analysis_id: str,
    plan_digest: str,
    resource_change_count: int,
    overall_risk_score: float,
    summary_json: dict[str, Any],
    summary_markdown: str,
) -> None:
    conn = await _conn()
    await conn.execute(
        """
        INSERT INTO terraform_analyses (
            id, plan_digest, resource_change_count,
            overall_risk_score, summary_json, summary_markdown
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            analysis_id,
            plan_digest,
            resource_change_count,
            overall_risk_score,
            json.dumps(summary_json),
            summary_markdown,
        ),
    )
    await conn.commit()


async def get_terraform_analysis(analysis_id: str) -> dict[str, Any] | None:
    conn = await _conn()
    cursor = await conn.execute(
        "SELECT * FROM terraform_analyses WHERE id = ?",
        (analysis_id,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


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


async def update_incident_type(incident_id: str, incident_type: str) -> None:
    conn = await _conn()
    await conn.execute(
        "UPDATE incidents SET incident_type = ? WHERE id = ?",
        (incident_type, incident_id),
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


async def upsert_service_baseline(
    server_id: str,
    service_name: str,
    *,
    cpu_p95: float | None = None,
    memory_p95: float | None = None,
    restart_rate_p95: float | None = None,
) -> None:
    conn = await _conn()
    await conn.execute(
        """
        INSERT INTO service_baselines (
            server_id, service_name, cpu_p95, memory_p95, restart_rate_p95, updated_at
        ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(server_id, service_name) DO UPDATE SET
            cpu_p95 = COALESCE(excluded.cpu_p95, service_baselines.cpu_p95),
            memory_p95 = COALESCE(excluded.memory_p95, service_baselines.memory_p95),
            restart_rate_p95 = COALESCE(
                excluded.restart_rate_p95, service_baselines.restart_rate_p95
            ),
            updated_at = CURRENT_TIMESTAMP
        """,
        (server_id, service_name, cpu_p95, memory_p95, restart_rate_p95),
    )
    await conn.commit()


async def insert_suppression_pattern(
    *,
    server_id: str,
    service_name: str | None,
    pattern_type: str,
    pattern_json: dict[str, Any],
    created_from_incident_id: str | None = None,
    expires_at: str | None = None,
) -> int:
    conn = await _conn()
    cursor = await conn.execute(
        """
        INSERT INTO suppression_patterns (
            server_id, service_name, pattern_type, pattern_json,
            created_from_incident_id, expires_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            server_id,
            service_name,
            pattern_type,
            json.dumps(pattern_json),
            created_from_incident_id,
            expires_at,
        ),
    )
    await conn.commit()
    return cursor.lastrowid or 0


async def list_suppression_patterns(
    server_id: str | None = None, *, active_only: bool = True
) -> list[dict[str, Any]]:
    conn = await _conn()
    query = "SELECT * FROM suppression_patterns WHERE 1=1"
    params: list[Any] = []
    if server_id:
        query += " AND server_id = ?"
        params.append(server_id)
    if active_only:
        query += " AND (expires_at IS NULL OR expires_at > datetime('now'))"
    query += " ORDER BY created_at DESC"
    cursor = await conn.execute(query, params)
    rows = []
    for row in await cursor.fetchall():
        data = dict(row)
        raw = data.get("pattern_json")
        if isinstance(raw, str):
            data["pattern"] = json.loads(raw or "{}")
        rows.append(data)
    return rows


async def delete_suppression_pattern(pattern_id: int) -> bool:
    conn = await _conn()
    cursor = await conn.execute(
        "DELETE FROM suppression_patterns WHERE id = ?", (pattern_id,)
    )
    await conn.commit()
    return (cursor.rowcount or 0) > 0


def _suppression_applies_to_service(
    pattern_service: str | None,
    anomaly_service: str | None,
) -> bool:
    """Scoped patterns (service set) only match that service; unset matches all."""
    if not pattern_service:
        return True
    if not anomaly_service:
        return False
    return pattern_service == anomaly_service


async def is_anomaly_suppressed(
    server_id: str,
    signature: str,
    service_name: str | None = None,
) -> bool:
    patterns = await list_suppression_patterns(server_id, active_only=True)
    for p in patterns:
        if p.get("pattern_type") != "anomaly_signature":
            continue
        pattern_service = p.get("service_name") or None
        if not _suppression_applies_to_service(pattern_service, service_name):
            continue
        pat = p.get("pattern") or {}
        if pat.get("signature") == signature:
            return True
        reason = pat.get("reason") or ""
        if reason and reason in signature:
            return True
    return False


async def increment_alert_fatigue(
    server_id: str,
    service_name: str,
    *,
    false_positive: bool = False,
    true_positive: bool = False,
) -> dict[str, Any]:
    from anomaly_detection import compute_fatigue_score

    conn = await _conn()
    cursor = await conn.execute(
        """
        SELECT * FROM service_alert_fatigue
        WHERE server_id = ? AND service_name = ?
        """,
        (server_id, service_name),
    )
    row = await cursor.fetchone()
    fp = (row["false_positive_count"] if row else 0) + (1 if false_positive else 0)
    tp = (row["true_positive_count"] if row else 0) + (1 if true_positive else 0)
    score = compute_fatigue_score(fp, tp)
    await conn.execute(
        """
        INSERT INTO service_alert_fatigue (
            server_id, service_name, false_positive_count,
            true_positive_count, fatigue_score, updated_at
        ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(server_id, service_name) DO UPDATE SET
            false_positive_count = excluded.false_positive_count,
            true_positive_count = excluded.true_positive_count,
            fatigue_score = excluded.fatigue_score,
            updated_at = CURRENT_TIMESTAMP
        """,
        (server_id, service_name, fp, tp, score),
    )
    await conn.commit()
    return await get_alert_fatigue(server_id, service_name) or {}


async def get_alert_fatigue(
    server_id: str, service_name: str
) -> dict[str, Any] | None:
    conn = await _conn()
    cursor = await conn.execute(
        """
        SELECT * FROM service_alert_fatigue
        WHERE server_id = ? AND service_name = ?
        """,
        (server_id, service_name),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def list_alert_fatigue() -> list[dict[str, Any]]:
    conn = await _conn()
    cursor = await conn.execute(
        "SELECT * FROM service_alert_fatigue ORDER BY fatigue_score DESC"
    )
    return [dict(r) for r in await cursor.fetchall()]


def _runbook_row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    data = dict(row)
    steps = data.get("steps")
    if isinstance(steps, str):
        data["steps"] = json.loads(steps or "[]")
    if not data.get("runbook_id") and data.get("id") is not None:
        data["runbook_id"] = str(data["id"])
    return data


async def get_runbook(
    service_name: str,
    incident_type: str,
    *,
    status: str | None = "approved",
) -> dict[str, Any] | None:
    conn = await _conn()
    query = """
        SELECT * FROM runbooks
        WHERE incident_type = ?
          AND COALESCE(service_name, '') = COALESCE(?, '')
    """
    params: list[Any] = [incident_type, service_name or None]
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY updated_at DESC LIMIT 1"
    cursor = await conn.execute(query, params)
    row = await cursor.fetchone()
    return _runbook_row_to_dict(row) if row else None


async def get_runbook_by_id(runbook_id: str) -> dict[str, Any] | None:
    conn = await _conn()
    cursor = await conn.execute(
        """
        SELECT * FROM runbooks
        WHERE runbook_id = ? OR CAST(id AS TEXT) = ?
        LIMIT 1
        """,
        (runbook_id, runbook_id),
    )
    row = await cursor.fetchone()
    return _runbook_row_to_dict(row) if row else None


async def list_runbooks(
    *,
    service_name: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    conn = await _conn()
    query = "SELECT * FROM runbooks WHERE 1=1"
    params: list[Any] = []
    if service_name:
        query += " AND service_name = ?"
        params.append(service_name)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY updated_at DESC"
    cursor = await conn.execute(query, params)
    return [_runbook_row_to_dict(r) for r in await cursor.fetchall()]


async def insert_runbook_draft(
    *,
    incident_type: str,
    service_name: str | None,
    steps: list[dict[str, Any]],
    source_incident_id: str | None = None,
    incident_signature: str | None = None,
) -> dict[str, Any]:
    import uuid as _uuid

    conn = await _conn()
    runbook_id = str(_uuid.uuid4())
    await conn.execute(
        """
        INSERT INTO runbooks (
            runbook_id, incident_type, service_name, steps,
            auto_executable, status, source_incident_id, incident_signature
        )
        VALUES (?, ?, ?, ?, 0, 'draft', ?, ?)
        """,
        (
            runbook_id,
            incident_type,
            service_name,
            json.dumps(steps),
            source_incident_id,
            incident_signature,
        ),
    )
    await conn.commit()
    row = await get_runbook_by_id(runbook_id)
    assert row is not None
    return row


async def approve_runbook(
    runbook_id: str,
    *,
    auto_executable: bool,
    approved_by: str = "dashboard",
) -> dict[str, Any] | None:
    conn = await _conn()
    await conn.execute(
        """
        UPDATE runbooks
        SET status = 'approved',
            auto_executable = ?,
            approved_at = CURRENT_TIMESTAMP,
            approved_by = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE runbook_id = ? OR CAST(id AS TEXT) = ?
        """,
        (1 if auto_executable else 0, approved_by, runbook_id, runbook_id),
    )
    await conn.commit()
    return await get_runbook_by_id(runbook_id)


async def archive_runbook(runbook_id: str) -> dict[str, Any] | None:
    conn = await _conn()
    await conn.execute(
        """
        UPDATE runbooks
        SET status = 'archived', updated_at = CURRENT_TIMESTAMP
        WHERE runbook_id = ? OR CAST(id AS TEXT) = ?
        """,
        (runbook_id, runbook_id),
    )
    await conn.commit()
    return await get_runbook_by_id(runbook_id)


async def update_runbook_steps(
    runbook_id: str, steps: list[dict[str, Any]]
) -> dict[str, Any] | None:
    conn = await _conn()
    await conn.execute(
        """
        UPDATE runbooks
        SET steps = ?, updated_at = CURRENT_TIMESTAMP
        WHERE (runbook_id = ? OR CAST(id AS TEXT) = ?) AND status = 'draft'
        """,
        (json.dumps(steps), runbook_id, runbook_id),
    )
    await conn.commit()
    return await get_runbook_by_id(runbook_id)


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


def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


# --- Fleet v2: managed servers & sites ---


async def list_managed_servers() -> list[dict[str, Any]]:
    conn = await _conn()
    cursor = await conn.execute(
        "SELECT * FROM managed_servers ORDER BY label, id"
    )
    rows = await cursor.fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["services"] = _json_loads(d.pop("services_json", None), [])
        d["thresholds"] = _json_loads(d.pop("thresholds_json", None), {})
        out.append(d)
    return out


async def get_managed_server(server_id: str) -> dict[str, Any] | None:
    conn = await _conn()
    cursor = await conn.execute(
        "SELECT * FROM managed_servers WHERE id = ?", (server_id,)
    )
    row = await cursor.fetchone()
    if not row:
        return None
    d = dict(row)
    d["services"] = _json_loads(d.pop("services_json", None), [])
    d["thresholds"] = _json_loads(d.pop("thresholds_json", None), {})
    return d


async def upsert_managed_server(
    server_id: str,
    *,
    label: str,
    host: str,
    port: int = 22,
    ssh_user: str = "root",
    ssh_key_path: str = "~/.ssh/id_ed25519",
    services: list[dict[str, Any]] | None = None,
    thresholds: dict[str, Any] | None = None,
) -> None:
    conn = await _conn()
    await conn.execute(
        """
        INSERT INTO managed_servers (
            id, label, host, port, ssh_user, ssh_key_path,
            services_json, thresholds_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            label = excluded.label,
            host = excluded.host,
            port = excluded.port,
            ssh_user = excluded.ssh_user,
            ssh_key_path = excluded.ssh_key_path,
            services_json = excluded.services_json,
            thresholds_json = excluded.thresholds_json,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            server_id,
            label,
            host,
            port,
            ssh_user,
            ssh_key_path,
            json.dumps(services or []),
            json.dumps(thresholds) if thresholds else None,
        ),
    )
    await conn.commit()


async def delete_managed_server(server_id: str) -> None:
    conn = await _conn()
    await conn.execute("DELETE FROM managed_servers WHERE id = ?", (server_id,))
    await conn.execute("DELETE FROM sites WHERE server_id = ?", (server_id,))
    await conn.commit()


async def count_managed_servers() -> int:
    conn = await _conn()
    cursor = await conn.execute("SELECT COUNT(*) FROM managed_servers")
    row = await cursor.fetchone()
    return int(row[0]) if row else 0


async def list_sites() -> list[dict[str, Any]]:
    conn = await _conn()
    cursor = await conn.execute(
        "SELECT * FROM sites ORDER BY client_name, name"
    )
    return [dict(r) for r in await cursor.fetchall()]


async def get_site(site_id: str) -> dict[str, Any] | None:
    conn = await _conn()
    cursor = await conn.execute("SELECT * FROM sites WHERE id = ?", (site_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def upsert_site(
    site_id: str,
    *,
    name: str,
    server_id: str,
    client_name: str | None = None,
    url: str | None = None,
    compose_file: str | None = None,
    service_name: str | None = None,
    environment: str = "production",
    repo_id: str | None = None,
    sensitive: bool = False,
) -> None:
    conn = await _conn()
    await conn.execute(
        """
        INSERT INTO sites (
            id, client_name, name, url, server_id, compose_file,
            service_name, environment, repo_id, sensitive, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            client_name = excluded.client_name,
            name = excluded.name,
            url = excluded.url,
            server_id = excluded.server_id,
            compose_file = excluded.compose_file,
            service_name = excluded.service_name,
            environment = excluded.environment,
            repo_id = excluded.repo_id,
            sensitive = excluded.sensitive,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            site_id,
            client_name,
            name,
            url,
            server_id,
            compose_file,
            service_name,
            environment,
            repo_id,
            1 if sensitive else 0,
        ),
    )
    await conn.commit()


async def delete_site(site_id: str) -> None:
    conn = await _conn()
    await conn.execute("DELETE FROM sites WHERE id = ?", (site_id,))
    await conn.commit()


async def update_site_uptime(
    site_id: str,
    *,
    uptime_status: str,
    uptime_status_code: int | None,
    uptime_latency_ms: float | None,
    ssl_expires_at: str | None = None,
) -> None:
    conn = await _conn()
    status = uptime_status if uptime_status == "up" else (
        "down" if uptime_status == "down" else "degraded"
    )
    await conn.execute(
        """
        UPDATE sites SET
            uptime_status = ?,
            uptime_status_code = ?,
            uptime_latency_ms = ?,
            uptime_checked_at = CURRENT_TIMESTAMP,
            ssl_expires_at = COALESCE(?, ssl_expires_at),
            status = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            uptime_status,
            uptime_status_code,
            uptime_latency_ms,
            ssl_expires_at,
            status,
            site_id,
        ),
    )
    await conn.commit()


async def get_setting(key: str) -> str | None:
    conn = await _conn()
    cursor = await conn.execute(
        "SELECT value FROM app_settings WHERE key = ?", (key,)
    )
    row = await cursor.fetchone()
    return row[0] if row else None


async def set_setting(key: str, value: str) -> None:
    conn = await _conn()
    await conn.execute(
        """
        INSERT INTO app_settings (key, value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = CURRENT_TIMESTAMP
        """,
        (key, value),
    )
    await conn.commit()


async def get_settings(prefix: str | None = None) -> dict[str, str]:
    conn = await _conn()
    if prefix:
        cursor = await conn.execute(
            "SELECT key, value FROM app_settings WHERE key LIKE ?",
            (f"{prefix}%",),
        )
    else:
        cursor = await conn.execute("SELECT key, value FROM app_settings")
    return {row[0]: row[1] for row in await cursor.fetchall()}
