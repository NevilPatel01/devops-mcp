"""MCP server tool registration and dispatch."""

from __future__ import annotations

import json
import logging
from typing import Any

import mcp.types as types
from mcp.server import NotificationOptions, Server

from tools import executor, incident, infrastructure

logger = logging.getLogger(__name__)

mcp_server = Server("devops-agent")

_INFRA_TOOLS = [
    ("get_server_health", infrastructure.get_server_health, ["server_id"]),
    ("list_containers", infrastructure.list_containers, ["server_id"]),
    (
        "get_container_logs",
        infrastructure.get_container_logs,
        ["server_id", "container_name"],
    ),
    (
        "get_docker_compose_status",
        infrastructure.get_docker_compose_status,
        ["server_id", "compose_file"],
    ),
    ("check_disk_usage", infrastructure.check_disk_usage, ["server_id"]),
    ("get_recent_events", infrastructure.get_recent_events, ["server_id"]),
]

_INCIDENT_TOOLS = [
    ("create_incident", incident.create_incident, None),
    ("correlate_incident", incident.correlate_incident, None),
    ("store_feedback_rule", incident.store_feedback_rule, None),
    ("list_pending_approvals", incident.list_pending_approvals, []),
    ("approve_action", incident.approve_action, ["action_id"]),
    ("reject_action", incident.reject_action, ["action_id", "feedback"]),
    ("draft_postmortem", incident.draft_postmortem, ["incident_id"]),
    ("get_oncall_handoff", incident.get_oncall_handoff, []),
    ("get_runbook", incident.get_runbook, ["service_name", "incident_type"]),
]

_EXEC_TOOLS = [
    ("restart_container", executor.restart_container, None),
    ("run_compose_command", executor.run_compose_command, None),
    ("run_ssh_command", executor.run_ssh_command, None),
    ("scale_service", executor.scale_service, None),
    ("rollback_deployment", executor.rollback_deployment, None),
]


def _tool_schema(name: str, required: list[str] | None) -> types.Tool:
    props: dict[str, Any] = {}
    req = required or []
    if "server_id" in req or required is None:
        props["server_id"] = {"type": "string"}
    if "container_name" in req or (required is None and name in ("get_container_logs",)):
        props["container_name"] = {"type": "string"}
    if "compose_file" in req:
        props["compose_file"] = {"type": "string"}
    if "action_id" in req or (required is None and name in _EXEC_TOOLS):
        props["action_id"] = {"type": "string"}
    if "feedback" in req:
        props["feedback"] = {"type": "string"}
    if "confirm_text" in req or name == "approve_action":
        props["confirm_text"] = {"type": "string"}
    if name == "create_incident":
        props = {
            "server_id": {"type": "string"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "severity": {"type": "string"},
            "service_name": {"type": "string"},
        }
        req = ["server_id", "title", "description", "severity"]
    elif name == "correlate_incident":
        props = {
            "server_id": {"type": "string"},
            "service_name": {"type": "string"},
            "minutes_back": {"type": "integer"},
        }
        req = ["server_id", "service_name"]
    elif name == "store_feedback_rule":
        props = {
            "action_type": {"type": "string"},
            "rule": {"type": "string"},
            "service_name": {"type": "string"},
            "server_id": {"type": "string"},
            "created_from_action_id": {"type": "string"},
        }
        req = ["action_type", "rule"]
    elif name == "reject_action":
        props = {"action_id": {"type": "string"}, "feedback": {"type": "string"}}
        req = ["action_id", "feedback"]
    elif name == "restart_container":
        props = {
            "server_id": {"type": "string"},
            "container_name": {"type": "string"},
            "action_id": {"type": "string"},
            "approved": {"type": "boolean"},
            "service_name": {"type": "string"},
        }
        req = ["server_id", "container_name", "action_id"]
    elif name == "run_compose_command":
        props = {
            "server_id": {"type": "string"},
            "compose_file": {"type": "string"},
            "command": {"type": "string"},
            "action_id": {"type": "string"},
            "approved": {"type": "boolean"},
            "service_name": {"type": "string"},
        }
        req = ["server_id", "compose_file", "command", "action_id"]
    elif name == "run_ssh_command":
        props = {
            "server_id": {"type": "string"},
            "command": {"type": "string"},
            "action_id": {"type": "string"},
            "approved": {"type": "boolean"},
            "risk_tier": {"type": "string"},
        }
        req = ["server_id", "command", "action_id"]
    elif name == "scale_service":
        props = {
            "server_id": {"type": "string"},
            "compose_file": {"type": "string"},
            "service_name": {"type": "string"},
            "replicas": {"type": "integer"},
            "action_id": {"type": "string"},
            "approved": {"type": "boolean"},
        }
        req = ["server_id", "compose_file", "service_name", "replicas", "action_id"]
    elif name == "rollback_deployment":
        props = {
            "server_id": {"type": "string"},
            "service_name": {"type": "string"},
            "compose_file": {"type": "string"},
            "action_id": {"type": "string"},
            "approved": {"type": "boolean"},
        }
        req = ["server_id", "service_name", "compose_file", "action_id"]

    return types.Tool(
        name=name,
        description=f"DevOps agent tool: {name}",
        inputSchema={
            "type": "object",
            "properties": props,
            "required": req if req else [],
        },
    )


_TOOL_DISPATCH: dict[str, Any] = {}


def _register(name: str, fn: Any) -> None:
    _TOOL_DISPATCH[name] = fn


for entry in _INFRA_TOOLS:
    _register(entry[0], entry[1])
for entry in _INCIDENT_TOOLS:
    _register(entry[0], entry[1])
for entry in _EXEC_TOOLS:
    _register(entry[0], entry[1])


@mcp_server.list_tools()
async def list_tools() -> list[types.Tool]:
    tools = []
    for entry in _INFRA_TOOLS:
        tools.append(_tool_schema(entry[0], entry[2]))
    for entry in _INCIDENT_TOOLS:
        tools.append(_tool_schema(entry[0], entry[2]))
    for entry in _EXEC_TOOLS:
        tools.append(_tool_schema(entry[0], entry[2]))
    return tools


@mcp_server.call_tool()
async def call_tool(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    args = arguments or {}
    fn = _TOOL_DISPATCH.get(name)
    if not fn:
        payload = {"success": False, "error": f"Unknown tool: {name}"}
    else:
        try:
            if name in ("list_pending_approvals", "get_oncall_handoff"):
                payload = await fn()
            elif name == "approve_action":
                payload = await fn(
                    args.get("action_id", ""),
                    confirm_text=args.get("confirm_text"),
                )
            else:
                payload = await fn(**args)
        except TypeError as exc:
            payload = {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("Tool %s failed", name)
            payload = {"success": False, "error": str(exc)}
    return [types.TextContent(type="text", text=json.dumps(payload, default=str))]


def initialization_options():
    return mcp_server.create_initialization_options(
        notification_options=NotificationOptions(tools_changed=False),
    )
