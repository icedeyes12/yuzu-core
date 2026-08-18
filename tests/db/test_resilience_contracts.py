"""Resilience & Concurrency Integration Tests (PostgreSQL, Connection Pools, Atomic Switches) ฅ^•ﻌ•^ฅ"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.db.connection import _POOL_TIMEOUT, AsyncPgSession, get_async_pool
from app.db.models_async import (
    create_session_async,
    get_all_sessions_async,
    switch_session_async,
)


@pytest.mark.asyncio
async def test_connection_pool_resilience_parameters() -> None:
    """Verify that the async pool is initialized with fast-failover limits."""
    pool = await get_async_pool()
    assert pool.timeout == _POOL_TIMEOUT
    assert pool.max_size == 10
    assert pool.min_size == 1


@pytest.mark.asyncio
async def test_switch_session_atomic_execution_path() -> None:
    """Verify that switch_session_async executes row locking and status activation in single transaction."""
    user_id = "019fa92e-f9be-7115-b000-70fb8c43438c"
    session_id = "019fa92e-f9be-7317-befb-913a4bbe7396"

    mock_execute = AsyncMock()
    mock_execute_returning = AsyncMock(return_value={"id": session_id})

    with patch("app.db.models_async.AsyncPgSession") as MockSession:
        instance = MockSession.return_value
        instance.__aenter__.return_value.execute = mock_execute
        instance.__aenter__.return_value.execute_returning = (
            mock_execute_returning
        )

        success = await switch_session_async(session_id, user_id)
        assert success is True

        # Verify SELECT ... FOR UPDATE row-locking was issued before deactivation
        assert mock_execute.call_count >= 2
        lock_call_query = mock_execute.call_args_list[0][0][0]
        assert "FOR UPDATE" in lock_call_query
