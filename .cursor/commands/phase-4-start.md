# Phase 4 — GitHub + postmortem + memory

Prerequisite: Phase 3 exit criteria met.

## Build order

1. `config/repos.yaml` — multi-repo (user fills owner/name/links)
2. `tools/cicd.py` — all five GitHub tools
3. Extend `correlate_incident` with Actions + commits timeline
4. `draft_postmortem`, `get_oncall_handoff`, `get_runbook` in `tools/incident.py`
5. `IncidentFeed.jsx`, `HandoffSummary.jsx`, `Incidents.jsx`
6. WebSocket `request_handoff` handler
7. Agent step 12 — postmortem on resolve

## Manual test

Trigger or simulate failed deploy → correlation mentions workflow → rollback on approval → postmortem in incident detail.

## README

Add demo GIF to `docs/assets/demo.gif` and uncomment in README.
