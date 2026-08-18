"""Unit and Integration Tests for Companion Memory Improvements (Threshold, Supersession, Privacy) ฅ^•ﻌ•^ฅ"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.memory.graph import GraphMemoryRepository


@pytest.mark.asyncio
async def test_search_nodes_vector_passes_min_score_threshold() -> None:
    """Verify that vector similarity search strictly passes minimum cosine score parameter."""
    user_id = "019fa92e-f9be-7115-b000-70fb8c43438c"
    dummy_embedding = [0.1] * 1536

    mock_fetchall = AsyncMock(return_value=[])
    with patch("app.memory.graph.pg_fetchall_async", mock_fetchall):
        _ = await GraphMemoryRepository.search_nodes_vector(
            user_id=user_id,
            embedding=dummy_embedding,
            min_score=0.75,
            limit=5,
        )

        assert mock_fetchall.called
        query_params = mock_fetchall.call_args[0][1]
        # Query parameters: (vector, user_id, dimensions, vector, min_score, limit)
        assert query_params[4] == 0.75
        assert query_params[5] == 5


@pytest.mark.asyncio
async def test_soft_delete_memory_node_privacy_flow() -> None:
    """Verify soft deletion sets status to deleted and bounds valid_until."""
    user_id = "019fa92e-f9be-7115-b000-70fb8c43438c"
    node_id = "019fa92e-f9be-7317-befb-913a4bbe7396"

    mock_fetchone = AsyncMock(return_value={"id": node_id})
    with patch("app.memory.graph.pg_fetchone_async", mock_fetchone):
        deleted = await GraphMemoryRepository.delete_node_soft(
            user_id=user_id, node_id=node_id
        )
        assert deleted is True

        query_str = mock_fetchone.call_args[0][0]
        assert "status = 'deleted'" in query_str
        assert "valid_until = NOW()" in query_str
