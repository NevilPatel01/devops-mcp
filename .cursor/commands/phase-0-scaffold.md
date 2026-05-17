# Phase 0 — Scaffold

Create the full project tree from `Project.md` §4 without implementing business logic yet.

## Steps

1. Create directories: `tools/`, `db/`, `models/`, `dashboard/src/{components,pages}`, `config/`, `tests/`.
2. Add `pyproject.toml`, `.env.example`, `db/schema.sql` (copy from Project.md §6).
3. Stub `db/store.py` with `init_db()` that runs schema.
4. Add empty `__init__.py` files and module stubs with docstrings only.
5. Scaffold Vite React app in `dashboard/` per Project.md §12.
6. Add `config/servers.yaml.example`, `config/rules.yaml`, `config/repos.yaml.example` (no real secrets).
7. Add `claude_desktop_config.json` (MCP SSE → `http://localhost:8080/mcp`).
8. Add `.gitignore`, MIT `LICENSE`, `.github/workflows/ci.yml` (pytest + ruff).
9. `config/servers.yaml.example` with `droplet`, `linode`, `protected_services`.

## Verify

- `pip install -e ".[dev]"` succeeds
- `cd dashboard && npm install && npm run build` succeeds
- Do **not** mark Phase 1 complete until poller shows real VPS data

## Reference

`docs/DEVELOPMENT_PLAN.md` — Phase 0
