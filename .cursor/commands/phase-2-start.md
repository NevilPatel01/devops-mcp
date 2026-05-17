# Phase 2 — Claude analysis + approval gate

Prerequisite: Phase 1 exit criteria met.

## Build order

1. `models/incident.py` — `Incident`, `ProposedAction`, `AnomalyEvent`
2. `tools/incident.py` — `create_incident`, `correlate_incident`, `store_feedback_rule`
3. `agent.py` — full loop steps 1–8 (plan only; execution stub)
4. Wire `poller.py` → `run_agent_loop` on anomaly
5. `server.py` — register MCP; shared `approve_action` / `reject_action` for WS + MCP
6. MCP: `list_pending_approvals`, `approve_action`, `reject_action` (chat fallback)
7. `ApprovalCard.jsx` + WebSocket handlers
8. `claude_desktop_config.json` with absolute `server.py` path
9. `tests/test_agent.py`

## Manual test

Kill a container on VPS → within ~30s see approval card with restart proposal and risk tier.

## Do not

Implement `tools/executor.py` write paths yet (Phase 3).
