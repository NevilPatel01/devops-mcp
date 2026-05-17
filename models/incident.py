"""Incident and action models (Phase 2+)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AnomalyEvent:
    server_id: str
    service_name: str | None
    reason: str
    severity: str = "medium"
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProposedAction:
    id: str
    incident_id: str | None
    action_type: str
    description: str
    rationale: str
    risk_tier: str
    rollback_plan: str
    parameters: dict[str, Any]
    status: str = "pending"


@dataclass
class Incident:
    id: str
    server_id: str
    title: str
    severity: str
    status: str = "open"
    service_name: str | None = None
    description: str | None = None


@dataclass
class ActionResult:
    action_id: str
    success: bool
    output: str = ""
    error: str | None = None
