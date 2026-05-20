"""Terraform plan JSON analyser (Phase 5) — deterministic scoring, optional Claude summary."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any

import yaml

from db import store

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RULES_PATH = ROOT / "config" / "terraform_rules.yaml"
MAX_CHANGES = 500

_DEFAULT_RULES: dict[str, Any] = {
    "naming": {
        "azurerm_linux_virtual_machine_prefix": "vm-",
        "required_tags": ["Environment", "Owner"],
        "regex_by_resource_type": {},
    },
    "risk_weights": {
        "delete": 10,
        "replace": 8,
        "create": 2,
        "update": 3,
        "no-op": 0,
    },
    "flagged_actions": ["delete", "replace"],
    "sensitive_resource_types": [
        "azurerm_postgresql_flexible_server",
        "azurerm_mssql_database",
        "azurerm_mysql_flexible_server",
    ],
}


def _rules_path() -> Path:
    raw = os.getenv("TERRAFORM_RULES_PATH", str(DEFAULT_RULES_PATH))
    return Path(raw).expanduser()


def load_terraform_rules(rules_path: Path | None = None) -> dict[str, Any]:
    path = rules_path or _rules_path()
    if not path.is_file():
        example = path.parent / "terraform_rules.yaml.example"
        if example.is_file():
            path = example
        else:
            return json.loads(json.dumps(_DEFAULT_RULES))
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    merged = json.loads(json.dumps(_DEFAULT_RULES))
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def _normalize_action(actions: list[str] | None) -> str:
    acts = set(actions or [])
    if not acts or acts == {"no-op"}:
        return "no-op"
    if "delete" in acts and "create" in acts:
        return "replace"
    if "delete" in acts:
        return "delete"
    if "create" in acts:
        return "create"
    if "update" in acts:
        return "update"
    return sorted(acts)[0]


def _resource_values(change_block: dict[str, Any]) -> dict[str, Any]:
    after = change_block.get("after")
    before = change_block.get("before")
    if isinstance(after, dict):
        return after
    if isinstance(before, dict):
        return before
    return {}


def parse_plan_json(
    plan_data: dict[str, Any],
    *,
    max_changes: int = MAX_CHANGES,
) -> tuple[list[dict[str, Any]], bool]:
    """Extract normalized resource change records from terraform show -json output."""
    raw_changes = plan_data.get("resource_changes")
    if raw_changes is None:
        return [], False
    if not isinstance(raw_changes, list):
        raise ValueError("resource_changes must be a list")

    truncated = len(raw_changes) > max_changes
    records: list[dict[str, Any]] = []
    for item in raw_changes[:max_changes]:
        if not isinstance(item, dict):
            continue
        change_block = item.get("change") or {}
        action = _normalize_action(change_block.get("actions"))
        records.append(
            {
                "address": item.get("address", ""),
                "type": item.get("type", ""),
                "name": item.get("name", ""),
                "action": action,
                "actions": change_block.get("actions") or [],
                "values": _resource_values(change_block),
            }
        )
    return records, truncated


def score_resource_change(record: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    weights = rules.get("risk_weights") or {}
    action = record["action"]
    base = float(weights.get(action, weights.get("update", 3)))
    modifiers: list[str] = []
    score = base

    resource_type = record.get("type") or ""
    sensitive_types = set(rules.get("sensitive_resource_types") or [])
    if resource_type in sensitive_types:
        score += 2.0
        modifiers.append("sensitive_resource_type")

    if action == "replace":
        modifiers.append("forces_replacement")

    score = min(10.0, round(score, 2))
    flagged = action in set(rules.get("flagged_actions") or [])
    return {
        "address": record["address"],
        "type": resource_type,
        "name": record.get("name", ""),
        "action": action,
        "risk_score": score,
        "flagged": flagged,
        "modifiers": modifiers,
    }


def check_naming_conventions(
    record: dict[str, Any],
    rules: dict[str, Any],
) -> list[dict[str, str]]:
    naming = rules.get("naming") or {}
    violations: list[dict[str, str]] = []
    resource_type = record.get("type") or ""
    name = record.get("name") or ""
    address = record.get("address") or ""

    prefix = naming.get("azurerm_linux_virtual_machine_prefix")
    if (
        resource_type == "azurerm_linux_virtual_machine"
        and prefix
        and not name.startswith(prefix)
    ):
        violations.append(
            {
                "address": address,
                "rule": "azurerm_linux_virtual_machine_prefix",
                "message": f"Name '{name}' must start with '{prefix}'",
            }
        )

    regex_map = naming.get("regex_by_resource_type") or {}
    pattern = regex_map.get(resource_type)
    if pattern and not re.match(pattern, name):
        violations.append(
            {
                "address": address,
                "rule": f"regex:{resource_type}",
                "message": f"Name '{name}' does not match /{pattern}/",
            }
        )

    required_tags = naming.get("required_tags") or []
    tags = record.get("values", {}).get("tags") or {}
    if isinstance(tags, dict):
        for tag in required_tags:
            if tag not in tags:
                violations.append(
                    {
                        "address": address,
                        "rule": "required_tags",
                        "message": f"Missing required tag: {tag}",
                    }
                )

    return violations


def build_summary_markdown(
    *,
    overall_risk_score: float,
    changes: list[dict[str, Any]],
    flagged_deletes: list[dict[str, Any]],
    naming_violations: list[dict[str, str]],
    truncated: bool,
    change_count: int,
) -> str:
    lines = [
        "## Terraform plan summary",
        "",
        f"- **Overall risk score:** {overall_risk_score}/10",
        f"- **Resource changes analyzed:** {change_count}",
    ]
    if truncated:
        lines.append("- **Note:** Plan truncated to max change limit.")
    lines.append("")

    if flagged_deletes:
        lines.append("### Flagged destructive changes")
        for item in flagged_deletes[:20]:
            lines.append(
                f"- `{item['address']}` — **{item['action']}** (score {item['risk_score']})"
            )
        lines.append("")

    if naming_violations:
        lines.append("### Naming / tagging violations")
        for v in naming_violations[:20]:
            lines.append(f"- `{v['address']}`: {v['message']}")
        lines.append("")

    high = sorted(changes, key=lambda c: c["risk_score"], reverse=True)[:10]
    if high:
        lines.append("### Highest-risk changes")
        for item in high:
            lines.append(
                f"- `{item['address']}` — {item['action']} (score {item['risk_score']})"
            )
        lines.append("")

    if not flagged_deletes and not naming_violations and overall_risk_score < 5:
        lines.append("No critical flags detected. Review changes before apply.")
    elif flagged_deletes:
        lines.append(
            "**Recommendation:** Review destructive changes carefully before apply."
        )

    return "\n".join(lines)


def _plan_digest(plan_data: dict[str, Any]) -> str:
    normalized = json.dumps(plan_data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _resolve_plan_path(plan_path: str) -> Path:
    raw = Path(plan_path).expanduser()
    allowed = os.getenv("TERRAFORM_PLAN_ALLOWED_DIR", "").strip()
    if allowed:
        base = Path(allowed).expanduser().resolve()
        resolved = (base / raw.name if not raw.is_absolute() else raw).resolve()
        if not str(resolved).startswith(str(base)):
            raise ValueError(f"plan_path must be under {base}")
        return resolved
    cwd = Path.cwd().resolve()
    resolved = raw.resolve() if raw.is_absolute() else (cwd / raw).resolve()
    if not str(resolved).startswith(str(cwd)):
        raise ValueError("plan_path must be under the current working directory")
    return resolved


def _load_plan_data(
    *,
    plan_json: str | None,
    plan_path: str | None,
) -> dict[str, Any]:
    if plan_json and plan_path:
        raise ValueError("Provide plan_json or plan_path, not both")
    if plan_json:
        return json.loads(plan_json)
    if plan_path:
        path = _resolve_plan_path(plan_path)
        if not path.is_file():
            raise FileNotFoundError(f"Plan file not found: {path}")
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    raise ValueError("plan_json or plan_path is required")


async def _maybe_claude_summary(markdown: str, changes: list[dict[str, Any]]) -> str:
    if os.getenv("TERRAFORM_SUMMARY_USE_CLAUDE", "false").lower() not in (
        "1",
        "true",
        "yes",
    ):
        return markdown
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key or api_key.startswith("sk-ant-..."):
        return markdown
    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=api_key)
        brief = json.dumps(changes[:30], default=str)
        message = await client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=800,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Rewrite this Terraform plan analysis for a PR comment "
                        "(plain English, bullet points, no jargon):\n\n"
                        f"{markdown}\n\nTop changes JSON:\n{brief}"
                    ),
                }
            ],
        )
        text = message.content[0].text if message.content else ""
        return text.strip() or markdown
    except Exception as exc:
        logger.warning("Claude terraform summary skipped: %s", exc)
        return markdown


def analyze_plan_data(
    plan_data: dict[str, Any],
    *,
    rules: dict[str, Any] | None = None,
    cache: bool = True,
) -> dict[str, Any]:
    """Synchronous core analysis (used by MCP tool and tests)."""
    rules = rules or load_terraform_rules()
    if "resource_changes" not in plan_data:
        return {
            "success": False,
            "error": "No resource_changes found in plan JSON",
        }

    records, truncated = parse_plan_json(plan_data)

    scored: list[dict[str, Any]] = []
    naming_violations: list[dict[str, str]] = []
    for record in records:
        scored.append(score_resource_change(record, rules))
        naming_violations.extend(check_naming_conventions(record, rules))

    flagged_deletes = [
        c for c in scored if c["action"] in ("delete", "replace") and c["flagged"]
    ]
    overall = 0.0
    if scored:
        overall = min(10.0, round(max(c["risk_score"] for c in scored), 2))

    summary_md = build_summary_markdown(
        overall_risk_score=overall,
        changes=scored,
        flagged_deletes=flagged_deletes,
        naming_violations=naming_violations,
        truncated=truncated,
        change_count=len(records),
    )

    findings = {
        "overall_risk_score": overall,
        "changes": scored,
        "flagged_deletes": flagged_deletes,
        "naming_violations": naming_violations,
        "truncated": truncated,
        "change_count": len(records),
    }

    analysis_id = str(uuid.uuid4())
    digest = _plan_digest(plan_data)

    return {
        "success": True,
        "error": None,
        "analysis_id": analysis_id,
        "plan_digest": digest,
        "overall_risk_score": overall,
        "changes": scored,
        "flagged_deletes": flagged_deletes,
        "naming_violations": naming_violations,
        "summary_markdown": summary_md,
        "summary_json": findings,
        "truncated": truncated,
        "_cache": cache,
    }


async def analyze_terraform_plan(
    plan_json: str | None = None,
    plan_path: str | None = None,
    rules_profile: str | None = None,
) -> dict[str, Any]:
    """MCP tool: analyse terraform plan -json output."""
    try:
        rules_path = Path(rules_profile) if rules_profile else None
        rules = load_terraform_rules(rules_path)
        plan_data = _load_plan_data(plan_json=plan_json, plan_path=plan_path)
        if not isinstance(plan_data, dict):
            return {"success": False, "error": "Plan JSON must be an object"}
        result = analyze_plan_data(plan_data, rules=rules)
        if not result.get("success"):
            return result

        summary_md = result["summary_markdown"]
        summary_md = await _maybe_claude_summary(summary_md, result["changes"])
        result["summary_markdown"] = summary_md

        await store.insert_terraform_analysis(
            analysis_id=result["analysis_id"],
            plan_digest=result["plan_digest"],
            resource_change_count=result["summary_json"]["change_count"],
            overall_risk_score=result["overall_risk_score"],
            summary_json=result["summary_json"],
            summary_markdown=summary_md,
        )
        result.pop("_cache", None)
        result.pop("summary_json", None)
        return result
    except json.JSONDecodeError as exc:
        return {"success": False, "error": f"Invalid JSON: {exc}"}
    except Exception as exc:
        logger.warning("analyze_terraform_plan failed: %s", exc)
        return {"success": False, "error": str(exc)}


async def get_terraform_analysis(analysis_id: str) -> dict[str, Any]:
    try:
        row = await store.get_terraform_analysis(analysis_id)
        if not row:
            return {"success": False, "error": "Analysis not found"}
        summary_json = row.get("summary_json")
        if isinstance(summary_json, str):
            summary_json = json.loads(summary_json)
        return {
            "success": True,
            "error": None,
            "analysis_id": row["id"],
            "created_at": row.get("created_at"),
            "plan_digest": row.get("plan_digest"),
            "overall_risk_score": row.get("overall_risk_score"),
            "summary_markdown": row.get("summary_markdown"),
            "summary_json": summary_json,
        }
    except Exception as exc:
        logger.warning("get_terraform_analysis failed: %s", exc)
        return {"success": False, "error": str(exc)}
