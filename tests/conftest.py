"""Shared pytest fixtures — keep CI fast and non-blocking."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import poller
from db import store


@pytest.fixture(scope="session", autouse=True)
def _block_real_poller_for_session():
    """server.py imports start_poller into its module; patch server, not only poller."""
    with (
        patch("server.start_poller", new_callable=AsyncMock),
        patch("server.stop_poller", new_callable=AsyncMock),
        patch("poller.start_poller", new_callable=AsyncMock),
        patch("approvals.broadcast_pending_actions", new_callable=AsyncMock),
    ):
        yield


@pytest.fixture(autouse=True)
async def _cleanup_after_test():
    yield
    await poller.stop_poller()
    await store.close_db()
