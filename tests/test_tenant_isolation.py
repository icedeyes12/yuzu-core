from __future__ import annotations

from app.db import queries as queries_mod


def _sql_constants(module):
    return {
        name: value
        for name, value in vars(module).items()
        if name.startswith("SQL_") and isinstance(value, str)
    }


def test_graph_sql_constants_are_tenant_scoped():
    graph_names = {name for name in _sql_constants(queries_mod) if "GRAPH" in name}
    assert graph_names
    for name in graph_names:
        sql = getattr(queries_mod, name)
        assert "user_id" in sql.lower(), name


def test_graph_schema_has_tenant_and_provenance_constraints():
    schema = "\n".join(queries_mod.SCHEMA_DDL)
    for table in ("episodes", "memory_nodes", "memory_edges", "memory_evidence"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in schema
        table_start = schema.index(f"CREATE TABLE IF NOT EXISTS {table}")
        table_end = schema.find('"""', table_start)
        assert "user_id UUID NOT NULL" in schema[table_start:table_end]
    assert "CHECK (node_id IS NOT NULL OR edge_id IS NOT NULL)" in schema


def test_legacy_memory_modules_are_deleted():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app" / "memory"
    for name in (
        "db_memory.py",
        "db_memory_facade.py",
        "db_memory_queries.py",
        "pcl.py",
        "review.py",
        "memory_review.py",
    ):
        assert not (root / name).exists(), name
