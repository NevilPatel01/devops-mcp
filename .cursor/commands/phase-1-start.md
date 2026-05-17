# Phase 1 — SSH poller + live dashboard

Implement Phase 1 from `docs/DEVELOPMENT_PLAN.md`. Follow `.cursor/rules/phases.mdc` — no agent, no executor.

## Build order

1. `models/config.py` + `models/server.py` — load `config/servers.yaml`
2. `db/store.py` — init schema, servers, snapshots, baselines CRUD
3. `tools/infrastructure.py` — all six **read-only** MCP-style functions (can register MCP in Phase 2; implement logic now)
4. `poller.py` — 30s asyncio loop, threshold anomaly flag, `ws_broadcast(snapshot_update)`
5. `server.py` — FastAPI, `/ws`, static `dashboard/dist`, start poller on startup
6. `dashboard/src/ws.js` + `ServerGrid.jsx` + `Dashboard.jsx`
7. `tests/test_infrastructure.py` — mock SSH

## Config

Copy `config/servers.yaml.example` → `config/servers.yaml`. Servers: `droplet`, `linode`, SSH `root`. Fill Q7 compose paths before real SSH works. Bind `127.0.0.1`. MCP: read-only tools + SSE `/mcp`.

## Exit criteria (all required)

- [ ] Dashboard at :8080 updates CPU/memory/disk/containers every ~30s
- [ ] Snapshots in SQLite
- [ ] Server card click shows container detail
- [ ] No `agent.py` execution path wired

## After complete

Tell user to record baseline behavior before Phase 2.
