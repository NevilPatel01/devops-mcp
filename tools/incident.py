"""Incident and memory MCP tools (Phase 2+)."""


async def create_incident(
    server_id: str,
    title: str,
    description: str,
    severity: str,
    service_name: str | None = None,
) -> dict:
    return {"success": False, "error": "Not implemented until Phase 2"}


async def correlate_incident(
    server_id: str,
    service_name: str,
    minutes_back: int = 30,
) -> dict:
    return {"success": False, "error": "Not implemented until Phase 2"}


async def store_feedback_rule(
    action_type: str,
    rule: str,
    service_name: str | None = None,
    server_id: str | None = None,
    created_from_action_id: str | None = None,
) -> dict:
    return {"success": False, "error": "Not implemented until Phase 2"}


async def draft_postmortem(incident_id: str) -> dict:
    return {"success": False, "error": "Not implemented until Phase 4"}


async def get_oncall_handoff() -> dict:
    return {"success": False, "error": "Not implemented until Phase 4"}


async def get_runbook(service_name: str, incident_type: str) -> dict:
    return {"success": False, "error": "Not implemented until Phase 4"}


async def list_pending_approvals() -> dict:
    return {"success": False, "error": "Not implemented until Phase 2"}


async def approve_action(action_id: str, confirm_text: str | None = None) -> dict:
    return {"success": False, "error": "Not implemented until Phase 2"}


async def reject_action(action_id: str, feedback: str) -> dict:
    return {"success": False, "error": "Not implemented until Phase 2"}
