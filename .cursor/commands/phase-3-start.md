# Phase 3 — Execution + rollback

Prerequisite: Phase 2 exit criteria met.

## Build order

1. `tools/executor.py` — all execution MCP tools per Project.md §7.2
2. Root `executor.py` — orchestration, `ws_broadcast`, `action_logs`
3. Wire agent steps 9–11 → `executor.execute`
4. `ExecutionLog.jsx` for `action_log_line`
5. Post-action health check + auto-rollback
6. LOW tier auto-execute per `config/rules.yaml`
7. `tests/test_executor.py`

## Manual test

Approve restart in dashboard → live `docker restart` output → container healthy → incident resolved.

## Safety

Confirm production VPS service names with user before first approved execute.
