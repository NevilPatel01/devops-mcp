"""GitHub Actions MCP tools — PyGithub, repo id resolved via config/repos.yaml."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from github import Github
from github.GithubException import GithubException

from models.config import RepoConfig, load_repos_config, repos_for_server_service

logger = logging.getLogger(__name__)


def _github_client() -> Github | None:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token or token.startswith("github_pat_..."):
        return None
    return Github(token)


async def _github_call(fn: Callable[[], Any]) -> Any:
    return await asyncio.to_thread(fn)


def resolve_repo(repo_id: str) -> RepoConfig | None:
    for repo in load_repos_config().repos:
        if repo.id == repo_id:
            return repo
    return None


def _full_name(repo: RepoConfig) -> str:
    return f"{repo.owner}/{repo.name}"


async def get_latest_workflow_run(repo: str, branch: str = "main") -> dict[str, Any]:
    try:
        cfg = resolve_repo(repo)
        if not cfg:
            return {"success": False, "error": f"Unknown repo id: {repo}"}
        gh = _github_client()
        if not gh:
            return {"success": False, "error": "GITHUB_TOKEN not configured in .env"}

        def _fetch():
            repository = gh.get_repo(_full_name(cfg))
            runs = repository.get_workflow_runs(branch=branch or cfg.default_branch)
            run = runs[0] if runs.totalCount else None
            return run

        run = await _github_call(_fetch)
        if not run:
            return {"success": True, "error": None, "run": None}
        head = run.head_commit
        return {
            "success": True,
            "error": None,
            "run_id": run.id,
            "status": run.status,
            "conclusion": run.conclusion,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "html_url": run.html_url,
            "head_commit": {
                "message": head.message if head else None,
                "author": head.author.login if head and head.author else None,
                "sha": head.sha if head else run.head_sha,
            },
            "repo": repo,
        }
    except GithubException as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        logger.warning("get_latest_workflow_run: %s", exc)
        return {"success": False, "error": str(exc)}


async def get_failed_step_logs(repo: str, run_id: int) -> dict[str, Any]:
    try:
        cfg = resolve_repo(repo)
        if not cfg:
            return {"success": False, "error": f"Unknown repo id: {repo}"}
        gh = _github_client()
        if not gh:
            return {"success": False, "error": "GITHUB_TOKEN not configured in .env"}

        def _fetch():
            repository = gh.get_repo(_full_name(cfg))
            run = repository.get_workflow_run(int(run_id))
            jobs = run.jobs()
            failed = []
            for job in jobs:
                if job.conclusion != "failure":
                    continue
                excerpt = ""
                try:
                    logs = job.get_logs()
                    if logs:
                        excerpt = logs.decode("utf-8", errors="replace")[-4000:]
                except Exception as log_exc:
                    excerpt = f"(could not fetch logs: {log_exc})"
                failed.append(
                    {
                        "name": job.name,
                        "conclusion": job.conclusion,
                        "log_excerpt": excerpt,
                    }
                )
            return failed

        failed_steps = await _github_call(_fetch)
        return {"success": True, "error": None, "failed_steps": failed_steps}
    except GithubException as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def get_recent_commits(repo: str, n: int = 5) -> dict[str, Any]:
    try:
        cfg = resolve_repo(repo)
        if not cfg:
            return {"success": False, "error": f"Unknown repo id: {repo}"}
        gh = _github_client()
        if not gh:
            return {"success": False, "error": "GITHUB_TOKEN not configured in .env"}

        def _fetch():
            repository = gh.get_repo(_full_name(cfg))
            commits = list(repository.get_commits(sha=cfg.default_branch))[: int(n)]
            out = []
            for c in commits:
                files_changed = len(c.files) if c.files else 0
                out.append(
                    {
                        "sha": c.sha,
                        "message": c.commit.message,
                        "author": c.commit.author.name if c.commit.author else None,
                        "timestamp": c.commit.author.date.isoformat()
                        if c.commit.author and c.commit.author.date
                        else None,
                        "files_changed": files_changed,
                    }
                )
            return out

        commits = await _github_call(_fetch)
        return {"success": True, "error": None, "commits": commits}
    except GithubException as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def get_deployment_diff(
    repo: str, base_sha: str, head_sha: str
) -> dict[str, Any]:
    try:
        cfg = resolve_repo(repo)
        if not cfg:
            return {"success": False, "error": f"Unknown repo id: {repo}"}
        gh = _github_client()
        if not gh:
            return {"success": False, "error": "GITHUB_TOKEN not configured in .env"}

        def _fetch():
            repository = gh.get_repo(_full_name(cfg))
            comp = repository.compare(base_sha, head_sha)
            files = []
            total = 0
            for f in comp.files:
                total += f.additions + f.deletions
                files.append(
                    {
                        "filename": f.filename,
                        "additions": f.additions,
                        "deletions": f.deletions,
                        "patch": (f.patch or "")[:2000],
                    }
                )
            return files, total

        files, total = await _github_call(_fetch)
        return {
            "success": True,
            "error": None,
            "files_changed": files,
            "total_changes": total,
        }
    except GithubException as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def trigger_workflow(
    repo: str,
    workflow_id: str,
    ref: str = "main",
    action_id: str | None = None,
    approved: bool = False,
) -> dict[str, Any]:
    try:
        if not approved:
            return {
                "success": False,
                "error": "trigger_workflow requires approval (MEDIUM risk)",
            }
        cfg = resolve_repo(repo)
        if not cfg:
            return {"success": False, "error": f"Unknown repo id: {repo}"}
        gh = _github_client()
        if not gh:
            return {"success": False, "error": "GITHUB_TOKEN not configured in .env"}

        def _dispatch():
            repository = gh.get_repo(_full_name(cfg))
            workflow = repository.get_workflow(workflow_id)
            workflow.create_dispatch(ref or cfg.default_branch)
            return datetime.now(UTC).isoformat()

        triggered_at = await _github_call(_dispatch)
        return {
            "success": True,
            "error": None,
            "workflow_id": workflow_id,
            "triggered_at": triggered_at,
            "action_id": action_id,
        }
    except GithubException as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def gather_deploy_context(
    server_id: str, service_name: str | None, minutes_back: int = 30
) -> dict[str, Any]:
    """Build GitHub correlation payload for correlate_incident."""
    repos_cfg = load_repos_config()
    linked = repos_for_server_service(repos_cfg, server_id, service_name)
    if not linked:
        return {"related_deploy": None, "github_timeline": [], "repos_checked": []}

    timeline: list[dict[str, Any]] = []
    related_deploy = None
    for repo in linked:
        run = await get_latest_workflow_run(repo.id, repo.default_branch)
        commits = await get_recent_commits(repo.id, 5)
        entry = {
            "repo_id": repo.id,
            "workflow_run": run if run.get("success") else None,
            "recent_commits": commits.get("commits") if commits.get("success") else [],
        }
        timeline.append(entry)
        if run.get("success") and run.get("run_id"):
            conclusion = run.get("conclusion")
            created = run.get("created_at")
            if conclusion in ("failure", "cancelled") or run.get("status") == "in_progress":
                related_deploy = {
                    "repo_id": repo.id,
                    "run_id": run["run_id"],
                    "conclusion": conclusion,
                    "status": run.get("status"),
                    "created_at": created,
                    "html_url": run.get("html_url"),
                    "head_sha": (run.get("head_commit") or {}).get("sha"),
                }
    return {
        "related_deploy": related_deploy,
        "github_timeline": timeline,
        "repos_checked": [r.id for r in linked],
    }
