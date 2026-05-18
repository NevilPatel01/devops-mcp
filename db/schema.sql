-- Run automatically on startup via store.py

CREATE TABLE IF NOT EXISTS servers (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    host TEXT NOT NULL,
    last_seen_at TIMESTAMP,
    status TEXT DEFAULT 'unknown'
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id TEXT NOT NULL,
    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    cpu_percent REAL,
    memory_percent REAL,
    disk_percent REAL,
    container_statuses JSON,
    raw_data JSON
);

CREATE TABLE IF NOT EXISTS baselines (
    server_id TEXT PRIMARY KEY,
    cpu_p95 REAL,
    memory_p95 REAL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    server_id TEXT NOT NULL,
    service_name TEXT,
    title TEXT NOT NULL,
    description TEXT,
    root_cause TEXT,
    status TEXT DEFAULT 'open',
    severity TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP,
    postmortem_draft TEXT,
    is_sensitive INTEGER DEFAULT 0,
    compliance_profile TEXT
);

CREATE TABLE IF NOT EXISTS compliance_audit_log (
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

CREATE TABLE IF NOT EXISTS proposed_actions (
    id TEXT PRIMARY KEY,
    incident_id TEXT,
    action_type TEXT NOT NULL,
    description TEXT NOT NULL,
    rationale TEXT NOT NULL,
    risk_tier TEXT NOT NULL,
    rollback_plan TEXT NOT NULL,
    parameters JSON NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TIMESTAMP,
    reviewer_feedback TEXT,
    stale_after_hours INTEGER DEFAULT 24
);

CREATE TABLE IF NOT EXISTS action_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    output TEXT,
    success BOOLEAN
);

CREATE TABLE IF NOT EXISTS feedback_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type TEXT NOT NULL,
    service_name TEXT,
    server_id TEXT,
    rule TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_from_action_id TEXT
);

CREATE TABLE IF NOT EXISTS runbooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_type TEXT NOT NULL,
    service_name TEXT,
    steps JSON NOT NULL,
    auto_executable BOOLEAN DEFAULT FALSE,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_snapshots_server_captured
    ON snapshots (server_id, captured_at);

CREATE INDEX IF NOT EXISTS idx_action_logs_action_id
    ON action_logs (action_id);

CREATE INDEX IF NOT EXISTS idx_compliance_audit_incident
    ON compliance_audit_log (incident_id, timestamp);

CREATE INDEX IF NOT EXISTS idx_compliance_audit_timestamp
    ON compliance_audit_log (timestamp);
