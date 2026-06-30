"""HTTP uptime checks for registered sites."""

from __future__ import annotations

import asyncio
import logging
import ssl
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from db import store
from ws_hub import ws_broadcast

logger = logging.getLogger(__name__)

_checker_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None

DEFAULT_INTERVAL = 60


def _normalize_url(url: str) -> str:
    u = url.strip()
    if not u:
        return u
    if not u.startswith(("http://", "https://")):
        u = f"https://{u}"
    return u


async def _check_one(site: dict) -> None:
    site_id = site["id"]
    raw_url = site.get("url")
    if not raw_url:
        return

    url = _normalize_url(raw_url)
    started = datetime.now(UTC)
    status = "unknown"
    code: int | None = None
    latency_ms: float | None = None
    ssl_expires: str | None = None

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(10.0, connect=8.0),
            verify=True,
        ) as client:
            t0 = asyncio.get_event_loop().time()
            resp = await client.get(url)
            latency_ms = round((asyncio.get_event_loop().time() - t0) * 1000, 1)
            code = resp.status_code
            if 200 <= code < 400:
                status = "up"
            elif code >= 500:
                status = "down"
            else:
                status = "degraded"
    except httpx.ConnectError:
        status = "down"
        code = 0
    except Exception as exc:
        logger.debug("Uptime check failed for %s: %s", site_id, exc)
        status = "down"

    if url.startswith("https://"):
        ssl_expires = await _fetch_ssl_expiry(url)

    await store.update_site_uptime(
        site_id,
        uptime_status=status,
        uptime_status_code=code,
        uptime_latency_ms=latency_ms,
        ssl_expires_at=ssl_expires,
    )

    await ws_broadcast(
        {
            "type": "site_update",
            "site_id": site_id,
            "data": {
                "site_id": site_id,
                "uptime_status": status,
                "uptime_status_code": code,
                "uptime_latency_ms": latency_ms,
                "uptime_checked_at": started.replace(microsecond=0).isoformat(),
                "ssl_expires_at": ssl_expires,
                "status": status,
            },
        }
    )


async def _fetch_ssl_expiry(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or 443
    if not host:
        return None

    def _sync() -> str | None:
        import socket

        try:
            ctx = ssl.create_default_context()
            raw = socket.create_connection((host, port), timeout=8)
            try:
                ssock = ctx.wrap_socket(raw, server_hostname=host)
                try:
                    cert = ssock.getpeercert()
                    exp = cert.get("notAfter")
                    if not exp:
                        return None
                    dt = datetime.strptime(exp, "%b %d %H:%M:%S %Y %Z")
                    return dt.replace(tzinfo=UTC).isoformat()
                finally:
                    ssock.close()
            finally:
                raw.close()
        except Exception:
            return None

    return await asyncio.to_thread(_sync)


async def _loop(interval: int) -> None:
    assert _stop_event is not None
    while not _stop_event.is_set():
        sites = await store.list_sites()
        with_url = [s for s in sites if s.get("url")]
        if with_url:
            await asyncio.gather(*[_check_one(s) for s in with_url], return_exceptions=True)
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=interval)
        except TimeoutError:
            pass


async def probe_site_by_id(site_id: str) -> dict:
    """Run an immediate HTTP uptime check for one site."""
    site = await store.get_site(site_id)
    if not site:
        return {"success": False, "error": "Site not found"}
    if not site.get("url"):
        return {"success": False, "error": "Site has no URL — add one to enable uptime checks"}
    await _check_one(site)
    updated = await store.get_site(site_id)
    return {"success": True, "site": updated}


async def start_uptime_checker(interval: int = DEFAULT_INTERVAL) -> None:
    global _checker_task, _stop_event
    if _checker_task and not _checker_task.done():
        return
    _stop_event = asyncio.Event()
    _checker_task = asyncio.create_task(_loop(interval), name="uptime_checker")
    logger.info("Uptime checker started (every %ss)", interval)


async def stop_uptime_checker() -> None:
    global _checker_task, _stop_event
    if _stop_event:
        _stop_event.set()
    if _checker_task:
        _checker_task.cancel()
        try:
            await _checker_task
        except asyncio.CancelledError:
            pass
        _checker_task = None
    _stop_event = None
