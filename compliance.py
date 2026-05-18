"""Compliance metadata, risk escalation, and policy hints (Phase 6)."""

from __future__ import annotations

import os
from typing import Any

from models.config import (
    ServerConfig,
    ServersFile,
    ServiceConfig,
    load_servers_config,
)

_PROFILE_HINTS: dict[str, list[str]] = {
    "hipaa": [
        "Document who approved remediation and when (audit trail).",
        "Assess likelihood of PHI exposure from the incident scope.",
        "Schedule access review if credentials or DB paths were involved.",
        "Retain relevant logs per organizational retention policy.",
    ],
    "pci": [
        "Verify cardholder data environment scope was not expanded.",
        "Review access logs for unauthorized changes.",
        "Confirm segmentation controls remained intact.",
    ],
    "none": [
        "Record remediation steps for operational audit.",
    ],
}


def compliance_strict_mode() -> bool:
    return os.getenv("COMPLIANCE_STRICT_MODE", "true").lower() not in (
        "0",
        "false",
        "no",
    )


def _servers_file() -> ServersFile | None:
    try:
        return load_servers_config()
    except FileNotFoundError:
        return None


def find_service(
    server: ServerConfig | None, service_name: str | None
) -> ServiceConfig | None:
    if not server or not service_name:
        return None
    for svc in server.services:
        if svc.name == service_name:
            return svc
    return None


def server_by_id(server_id: str) -> ServerConfig | None:
    cfg = _servers_file()
    if not cfg:
        return None
    for s in cfg.servers:
        if s.id == server_id:
            return s
    return None


def resolve_service_name(
    server: ServerConfig | None,
    *,
    service_name: str | None,
    container_name: str | None = None,
) -> str | None:
    if service_name:
        return service_name
    if not server or not container_name:
        return None
    name_lower = container_name.lower()
    for svc in server.services:
        if svc.name.lower() in name_lower or name_lower in svc.name.lower():
            return svc.name
    return None


def service_compliance_meta(
    server_id: str | None,
    service_name: str | None,
    *,
    container_name: str | None = None,
) -> dict[str, Any]:
    """Return sensitive flag, profile, and policy hints for a service."""
    cfg = _servers_file()
    server = server_by_id(server_id) if server_id else None
    resolved = resolve_service_name(
        server, service_name=service_name, container_name=container_name
    )
    svc = find_service(server, resolved)
    sensitive = bool(svc and svc.sensitive)
    default_profile = "none"
    if cfg and cfg.compliance:
        default_profile = cfg.compliance.default_profile or "none"
    profile = (svc.compliance_profile if svc and svc.compliance_profile else None) or (
        default_profile if sensitive else "none"
    )
    return {
        "sensitive": sensitive,
        "compliance_profile": profile,
        "service_name": resolved,
        "policy_hints": _PROFILE_HINTS.get(profile, _PROFILE_HINTS["none"]),
    }


def incident_compliance_fields(
    server_id: str, service_name: str | None
) -> dict[str, Any]:
    meta = service_compliance_meta(server_id, service_name)
    return {
        "is_sensitive": 1 if meta["sensitive"] else 0,
        "compliance_profile": meta["compliance_profile"],
    }


def is_sensitive_service(server_id: str | None, service_name: str | None) -> bool:
    return bool(service_compliance_meta(server_id, service_name)["sensitive"])


def bump_risk_for_sensitive(
    risk_tier: str, server_id: str | None, service_name: str | None
) -> str:
    risk = (risk_tier or "medium").lower()
    if risk == "low" and is_sensitive_service(server_id, service_name):
        return "medium"
    return risk


def compliance_warning_message(profile: str) -> str:
    label = profile.upper() if profile and profile != "none" else "SENSITIVE"
    return (
        f"This action touches a compliance-regulated service ({label}). "
        "Review audit implications before approving."
    )


def requires_compliance_ack(risk_tier: str, compliance_sensitive: bool) -> bool:
    return compliance_sensitive and (risk_tier or "").lower() == "high"
