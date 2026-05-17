"""WebSocket broadcast hub for dashboard clients."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket

_clients: set[WebSocket] = set()
_lock = asyncio.Lock()


async def register(ws: WebSocket) -> None:
    await ws.accept()
    async with _lock:
        _clients.add(ws)


async def unregister(ws: WebSocket) -> None:
    async with _lock:
        _clients.discard(ws)


async def ws_broadcast(message: dict[str, Any]) -> None:
    """Send JSON message to all connected dashboard clients."""
    payload = json.dumps(message)
    async with _lock:
        dead: list[WebSocket] = []
        for client in _clients:
            try:
                await client.send_text(payload)
            except Exception:
                dead.append(client)
        for client in dead:
            _clients.discard(client)


def client_count() -> int:
    return len(_clients)
