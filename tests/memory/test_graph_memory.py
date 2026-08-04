from __future__ import annotations

import pytest

from app.db.queries import (
    SCHEMA_DDL,
    SQL_GRAPH_EDGE_UPSERT,
    SQL_GRAPH_EVIDENCE_INSERT,
    SQL_GRAPH_NODE_ARCHIVE,
    SQL_GRAPH_NODE_EXPAND,
    SQL_GRAPH_NODE_SEARCH_TEXT,
)


def test_graph_schema_is_tenant_scoped_and_provenance_backed():
    schema = "\n".join(SCHEMA_DDL)
    for table in ("episodes", "memory_nodes", "memory_edges", "memory_evidence"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in schema
        assert "user_id UUID NOT NULL" in schema
    assert "CHECK (node_id IS NOT NULL OR edge_id IS NOT NULL)" in schema
    assert "CREATE OR REPLACE VIEW relationships" in schema


def test_graph_queries_require_tenant_scope():
    assert "user_id = %s" in SQL_GRAPH_NODE_SEARCH_TEXT
    assert "e.user_id = %s" in SQL_GRAPH_NODE_EXPAND
    assert (
        "ON CONFLICT (user_id, from_node_id, to_node_id, edge_type)"
        in SQL_GRAPH_EDGE_UPSERT
    )
    assert "user_id" in SQL_GRAPH_EVIDENCE_INSERT


def test_graph_archive_locks_canonical_and_candidate():
    assert "ORDER BY id" in SQL_GRAPH_NODE_ARCHIVE
    assert "FOR UPDATE" in SQL_GRAPH_NODE_ARCHIVE
    assert SQL_GRAPH_NODE_ARCHIVE.count("status = 'active'") >= 3


@pytest.mark.asyncio
async def test_consolidate_node_preserves_negations(monkeypatch):
    """Test that negated facts are NOT archived as duplicates."""
    from app.memory.graph import GraphMemoryRepository

    candidates = [
        {"id": "node-2", "content": "Alice likes Bob"},
        {"id": "node-3", "content": "Alice does not like Bob"},
    ]

    async def mock_find_similar(*args, **kwargs):
        return candidates

    archived_calls = []

    async def mock_archive(*, user_id, node_id, canonical_node_id):
        archived_calls.append((node_id, canonical_node_id))
        return True

    monkeypatch.setattr(
        GraphMemoryRepository, "find_similar_active_nodes", mock_find_similar
    )
    monkeypatch.setattr(GraphMemoryRepository, "archive_node", mock_archive)

    result = await GraphMemoryRepository.consolidate_node(
        user_id="user-1",
        node_id="node-1",
        node_type="fact",
        content="Alice likes Bob",
    )

    # Only "Alice likes Bob" should be archived (exact match)
    # "Alice does not like Bob" should NOT be archived (different meaning)
    assert result["candidates"] == 2
    assert result["archived"] == 1
    assert archived_calls == [("node-2", "node-1")]


@pytest.mark.asyncio
async def test_consolidate_node_preserves_qualifiers(monkeypatch):
    """Test that qualified facts are NOT archived as duplicates."""
    from app.memory.graph import GraphMemoryRepository

    candidates = [
        {"id": "node-2", "content": "Alice is doctor"},
        {"id": "node-3", "content": "Alice is great doctor"},
    ]

    async def mock_find_similar(*args, **kwargs):
        return candidates

    archived_calls = []

    async def mock_archive(*, user_id, node_id, canonical_node_id):
        archived_calls.append((node_id, canonical_node_id))
        return True

    monkeypatch.setattr(
        GraphMemoryRepository, "find_similar_active_nodes", mock_find_similar
    )
    monkeypatch.setattr(GraphMemoryRepository, "archive_node", mock_archive)

    result = await GraphMemoryRepository.consolidate_node(
        user_id="user-1",
        node_id="node-1",
        node_type="fact",
        content="Alice is doctor",
    )

    # Only "Alice is doctor" should be archived (exact match)
    # "Alice is great doctor" should NOT be archived (more specific)
    assert result["candidates"] == 2
    assert result["archived"] == 1
    assert archived_calls == [("node-2", "node-1")]


@pytest.mark.asyncio
async def test_consolidate_node_preserves_reordered_words(monkeypatch):
    """Test that facts with reordered words are NOT archived as duplicates."""
    from app.memory.graph import GraphMemoryRepository

    candidates = [
        {"id": "node-2", "content": "Alice visited Paris France"},
        {"id": "node-3", "content": "Alice visited France Paris"},
    ]

    async def mock_find_similar(*args, **kwargs):
        return candidates

    archived_calls = []

    async def mock_archive(*, user_id, node_id, canonical_node_id):
        archived_calls.append((node_id, canonical_node_id))
        return True

    monkeypatch.setattr(
        GraphMemoryRepository, "find_similar_active_nodes", mock_find_similar
    )
    monkeypatch.setattr(GraphMemoryRepository, "archive_node", mock_archive)

    result = await GraphMemoryRepository.consolidate_node(
        user_id="user-1",
        node_id="node-1",
        node_type="fact",
        content="Alice visited Paris France",
    )

    # Only "Alice visited Paris France" should be archived (exact match)
    # "Alice visited France Paris" should NOT be archived (different order)
    assert result["candidates"] == 2
    assert result["archived"] == 1
    assert archived_calls == [("node-2", "node-1")]


@pytest.mark.asyncio
async def test_consolidate_node_exact_match_archives(monkeypatch):
    """Test that exact matches ARE archived."""
    from app.memory.graph import GraphMemoryRepository

    candidates = [
        {"id": "node-2", "content": "Alice likes programming"},
        {"id": "node-3", "content": "Alice Likes Programming"},  # Case variation
    ]

    async def mock_find_similar(*args, **kwargs):
        return candidates

    archived_calls = []

    async def mock_archive(*, user_id, node_id, canonical_node_id):
        archived_calls.append((node_id, canonical_node_id))
        return True

    monkeypatch.setattr(
        GraphMemoryRepository, "find_similar_active_nodes", mock_find_similar
    )
    monkeypatch.setattr(GraphMemoryRepository, "archive_node", mock_archive)

    result = await GraphMemoryRepository.consolidate_node(
        user_id="user-1",
        node_id="node-1",
        node_type="fact",
        content="Alice likes programming",
    )

    # Both should be archived (case-insensitive exact match)
    assert result["candidates"] == 2
    assert result["archived"] == 2
    assert len(archived_calls) == 2
