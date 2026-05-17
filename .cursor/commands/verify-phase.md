# Verify current phase

Run the checklist for the active phase in `docs/DEVELOPMENT_PLAN.md`.

## Process

1. Read phase exit criteria in the plan doc.
2. List implemented files vs spec in `Project.md` §4.
3. Run tests: `pytest tests/ -v`
4. If Phase ≥1: confirm `python server.py` starts and dashboard loads.
5. Report: pass/fail per criterion, blockers, and whether next phase may start.

## Do not

Advance phase if any exit criterion fails.
