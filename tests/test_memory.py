from app.db.queries import (
    SCHEMA_DDL,
    SQL_GRAPH_NODE_EXPAND,
    SQL_GRAPH_NODE_SEARCH_TEXT,
    SQL_GRAPH_NODE_SEARCH_VECTOR,
)
from app.memory.graph import vector_literal


def test_graph_schema_is_the_memory_storage_owner():
    schema = "\n".join(SCHEMA_DDL)
    for table in ("episodes", "memory_nodes", "memory_edges", "memory_evidence"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in schema
    assert "CREATE TABLE IF NOT EXISTS semantic_facts" not in schema
    assert "DROP TABLE IF EXISTS semantic_facts" in schema


def test_graph_queries_are_tenant_scoped():
    assert "user_id = %s" in SQL_GRAPH_NODE_SEARCH_TEXT
    assert "user_id = %s" in SQL_GRAPH_NODE_SEARCH_VECTOR
    assert "e.user_id = %s" in SQL_GRAPH_NODE_EXPAND


def test_vector_literal():
    assert vector_literal(None) is None
    assert vector_literal([]) == "[]"
    assert vector_literal([0.1, 0.2]) == "[0.1,0.2]"
