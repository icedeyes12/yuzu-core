from __future__ import annotations

from app.db.queries import (
    SCHEMA_DDL,
    SQL_GRAPH_EDGE_UPSERT,
    SQL_GRAPH_EVIDENCE_INSERT,
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
