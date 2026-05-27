"""Incident and memory MCP tools."""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

from anthropic import AsyncAnthropic

from compliance import incident_compliance_fields
from db import store
from models.config import load_app_config
from runbook_engine import draft_runbook_from_incident
from tools import cicd

logger = logging.getLogger(__name__)
POSTMORTEM_MODEL = "claude-sonnet-4-5"


async def create_incident(
    server_id: str,
    title: str,
    description: str,
    severity: str,
    service_name: str | None = None,
) -> dict[str, Any]:
    try:
        incident_id = str(uuid.uuid4())
        compliance_fields = incident_compliance_fields(server_id, service_name)
        row = await store.create_incident(
            incident_id,
            server_id,
            title,
            description,
            severity,
            service_name=service_name,
            **compliance_fields,
        )
        await store.insert_compliance_audit(
            "incident_created",
            server_id=server_id,
            service_name=service_name,
            incident_id=incident_id,
            actor="mcp",
            details={
                "severity": severity,
                "is_sensitive": compliance_fields.get("is_sensitive"),
                "compliance_profile": compliance_fields.get("compliance_profile"),
            },
        )
        return {
            "success": True,
            "error": None,
            "incident_id": incident_id,
            "created_at": row.get("created_at"),
            "incident": row,
        }
    except Exception as exc:
        logger.warning("create_incident failed: %s", exc)
        return {"success": False, "error": str(exc)}


async def correlate_incident(
    server_id: str,
    service_name: str,
    minutes_back: int = 30,
) -> dict[str, Any]:
    try:
        cfg = load_app_config()
        window = cfg.rules.automation.correlation_window_minutes
        if minutes_back <= 0:
            minutes_back = window

        snapshots = await store.get_snapshots_for_incident_window(
            server_id, minutes=minutes_back
        )
        timeline = []
        for snap in snapshots:
            timeline.append(
                {
                    "captured_at": snap.get("captured_at"),
                    "cpu_percent": snap.get("cpu_percent"),
                    "memory_percent": snap.get("memory_percent"),
                    "disk_percent": snap.get("disk_percent"),
                    "containers": snap.get("container_statuses") or [],
                }
            )

        rules = await store.list_feedback_rules(
            server_id=server_id, service_name=service_name
        )
        similar = await store.find_similar_incidents(server_id, service_name, limit=5)
        github_ctx = await cicd.gather_deploy_context(
            server_id, service_name, minutes_back=minutes_back
        )

        likely_cause = "Unknown"
        if timeline:
            latest = timeline[0]
            containers = latest.get("containers") or []
            unhealthy = [
                c
                for c in containers
                if "exited" in (c.get("status") or "").lower()
                or "restarting" in (c.get("status") or "").lower()
            ]
            if unhealthy:
                names = ", ".join(c.get("name", "?") for c in unhealthy[:3])
                likely_cause = f"Unhealthy containers detected: {names}"

        related = github_ctx.get("related_deploy")
        if related:
            likely_cause = (
                f"Recent GitHub Actions run on {related.get('repo_id')}: "
                f"{related.get('conclusion') or related.get('status')} "
                f"({related.get('created_at')})"
            )

        return {
            "success": True,
            "error": None,
            "timeline": timeline,
            "likely_cause": likely_cause,
            "related_deploy": related,
            "github_timeline": github_ctx.get("github_timeline"),
            "similar_incidents": similar,
            "rules_to_respect": [r["rule"] for r in rules],
            "minutes_back": minutes_back,
        }
    except Exception as exc:
        logger.warning("correlate_incident failed: %s", exc)
        return {"success": False, "error": str(exc)}


async def store_feedback_rule(
    action_type: str,
    rule: str,
    service_name: str | None = None,
    server_id: str | None = None,
    created_from_action_id: str | None = None,
) -> dict[str, Any]:
    try:
        rule_id = await store.insert_feedback_rule(
            action_type,
            rule,
            service_name=service_name,
            server_id=server_id,
            created_from_action_id=created_from_action_id,
        )
        return {"success": True, "error": None, "rule_id": rule_id}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def _claude_markdown(system: str, user: str) -> str | None:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key or api_key.startswith("sk-ant-..."):
        return None
    client = AsyncAnthropic(api_key=api_key)
    response = await client.messages.create(
        model=POSTMORTEM_MODEL,
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    parts = [b.text for b in response.content if hasattr(b, "text")]
    return "".join(parts).strip() or None


async def draft_postmortem(incident_id: str) -> dict[str, Any]:
    try:
        incident = await store.get_incident(incident_id)
        if not incident:
            return {"success": False, "error": f"Unknown incident_id: {incident_id}"}

        actions = await store.get_actions_for_incident(incident_id)
        logs = []
        for action in actions:
            for log in await store.get_action_logs(action["id"]):
                logs.append(
                    {
                        "action_id": action["id"],
                        "success": log.get("success"),
                        "output": (log.get("output") or "")[:2000],
                    }
                )

        snapshots = await store.get_snapshots_for_incident_window(
            incident["server_id"], minutes=60, limit=30
        )
        correlation = await correlate_incident(
            incident["server_id"],
            incident.get("service_name") or "unknown",
        )

        context = {
            "incident": incident,
            "actions": actions,
            "action_logs": logs,
            "snapshots": snapshots[-10:],
            "correlation": correlation,
        }
        profile = incident.get("compliance_profile") or "none"
        is_sensitive = bool(incident.get("is_sensitive"))
        compliance_section = ""
        if is_sensitive:
            if profile == "hipaa":
                compliance_section = (
                    " Required section **Compliance impact** (HIPAA-aware): "
                    "data exposure likelihood, audit trail references, "
                    "access review and log retention follow-ups."
                )
            elif profile == "pci":
                compliance_section = (
                    " Required section **Compliance impact** (PCI-aware): "
                    "CDE scope, access/log review, segmentation validation."
                )
            else:
                compliance_section = (
                    " Required section **Compliance impact**: operational audit notes "
                    "and recommended follow-ups."
                )
        system = (
            "Write a blameless postmortem in markdown. Sections: Timeline, Root Cause, "
            "Impact, What went well, What went wrong, Action items."
            f"{compliance_section}"
        )
        body = await _claude_markdown(system, json.dumps(context, default=str))
        if not body:
            body = (
                f"# Postmortem — {incident.get('title')}\n\n"
                f"**Status:** {incident.get('status')}\n\n"
                f"{incident.get('description')}\n\n"
                "_Auto-draft unavailable (ANTHROPIC_API_KEY missing)._"
            )

        await store.update_incident_postmortem(incident_id, body)
        if is_sensitive:
            await store.insert_compliance_audit(
                "postmortem_drafted",
                server_id=incident.get("server_id"),
                service_name=incident.get("service_name"),
                incident_id=incident_id,
                actor="mcp",
                details={"compliance_profile": profile},
            )
        return {
            "success": True,
            "error": None,
            "postmortem_markdown": body,
            "incident_id": incident_id,
        }
    except Exception as exc:
        logger.warning("draft_postmortem failed: %s", exc)
        return {"success": False, "error": str(exc)}


async def get_oncall_handoff() -> dict[str, Any]:
    try:
        from datetime import UTC, datetime

        open_incidents = await store.list_open_incidents()
        pending = await store.list_pending_actions()
        recent_actions = await store.list_recent_actions(hours=8)
        cfg = load_app_config()

        repo_status = []
        for repo in cfg.repos.repos:
            run = await cicd.get_latest_workflow_run(repo.id, repo.default_branch)
            repo_status.append(
                {
                    "repo_id": repo.id,
                    "workflow": run if run.get("success") else {"error": run.get("error")},
                }
            )

        payload = {
            "generated_at": datetime.now(UTC).isoformat(),
            "open_incidents": open_incidents,
            "pending_approvals": pending,
            "recent_actions": recent_actions,
            "repo_workflows": repo_status,
        }
        system = (
            "Write an on-call handoff summary in markdown for the next shift. "
            "Cover open incidents, pending approvals, recent actions, and CI status."
        )
        md = await _claude_markdown(system, json.dumps(payload, default=str))
        if not md:
            lines = [
                "# Oncall handoff",
                f"Generated: {payload['generated_at']}",
                "",
                f"## Open incidents ({len(open_incidents)})",
            ]
            for inc in open_incidents[:10]:
                lines.append(f"- **{inc.get('title')}** ({inc.get('server_id')})")
            lines.append(f"\n## Pending approvals ({len(pending)})")
            for a in pending[:10]:
                lines.append(f"- {a.get('description')} [{a.get('risk_tier')}]")
            md = "\n".join(lines)

        return {
            "success": True,
            "error": None,
            "handoff_markdown": md,
            "generated_at": payload["generated_at"],
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def get_runbook(service_name: str, incident_type: str) -> dict[str, Any]:
    try:
        row = await store.get_runbook(
            service_name, incident_type, status=None
        )
        if not row:
            return {
                "success": True,
                "error": None,
                "found": False,
                "steps": [],
                "auto_executable": False,
            }
        return {
            "success": True,
            "error": None,
            "found": True,
            "runbook_id": row.get("runbook_id"),
            "status": row.get("status") or "draft",
            "steps": row.get("steps") or [],
            "auto_executable": bool(row.get("auto_executable")),
            "incident_type": row.get("incident_type"),
            "service_name": row.get("service_name"),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def list_runbooks(
    service_name: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    try:
        rows = await store.list_runbooks(
            service_name=service_name or None,
            status=status or None,
        )
        return {"success": True, "error": None, "runbooks": rows}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def propose_runbook_from_incident(incident_id: str) -> dict[str, Any]:
    try:
        return await draft_runbook_from_incident(incident_id)
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def approve_runbook(
    runbook_id: str,
    auto_executable: bool = False,
    approved_by: str = "mcp",
) -> dict[str, Any]:
    try:
        row = await store.approve_runbook(
            runbook_id,
            auto_executable=auto_executable,
            approved_by=approved_by,
        )
        if not row:
            return {"success": False, "error": "Runbook not found"}
        return {"success": True, "error": None, "runbook": row}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def archive_runbook(runbook_id: str) -> dict[str, Any]:
    try:
        row = await store.archive_runbook(runbook_id)
        if not row:
            return {"success": False, "error": "Runbook not found"}
        return {"success": True, "error": None, "runbook": row}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def list_pending_approvals() -> dict[str, Any]:
    try:
        pending = await store.list_pending_actions()
        return {
            "success": True,
            "error": None,
            "actions": [
                {
                    "id": a["id"],
                    "action_type": a["action_type"],
                    "description": a["description"],
                    "risk_tier": a["risk_tier"],
                    "parameters": a.get("parameters") or {},
                    "created_at": a.get("created_at"),
                }
                for a in pending
            ],
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def approve_action(
    action_id: str,
    confirm_text: str | None = None,
    compliance_confirm_text: str | None = None,
) -> dict[str, Any]:
    from approvals import approve_action_by_id

    try:
        return await approve_action_by_id(
            action_id,
            source="mcp",
            confirm_text=confirm_text,
            compliance_confirm_text=compliance_confirm_text,
        )
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def reject_action(action_id: str, feedback: str) -> dict[str, Any]:
    from approvals import reject_action_by_id

    try:
        return await reject_action_by_id(action_id, feedback)
    except Exception as exc:
        return {"success": False, "error": str(exc)}
