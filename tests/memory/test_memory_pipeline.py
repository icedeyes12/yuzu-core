import pytest

from app.db.queries import (
    SCHEMA_DDL,
    SQL_GRAPH_NODE_EXPAND,
    SQL_GRAPH_NODE_SEARCH_TEXT,
    SQL_GRAPH_NODE_SEARCH_VECTOR,
    SQL_PIPELINE_STATE_CLAIM,
    SQL_PIPELINE_STATE_CLEAR,
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


def test_pipeline_fence_sql_is_atomic_and_tenant_scoped():
    assert "UPDATE chat_sessions" in SQL_PIPELINE_STATE_CLAIM
    assert "WHERE id = %s" in SQL_PIPELINE_STATE_CLAIM
    assert "AND user_id = %s" in SQL_PIPELINE_STATE_CLAIM
    assert "RETURNING memory_pipeline_state" in SQL_PIPELINE_STATE_CLAIM
    assert (
        "memory_pipeline_state - 'in_progress_fence_count'" in SQL_PIPELINE_STATE_CLEAR
    )
    assert "AND user_id = %s" in SQL_PIPELINE_STATE_CLEAR


@pytest.mark.asyncio
async def test_scheduler_thresholds(monkeypatch):
    from app.memory import memory

    async def state(_session_id, user_id):
        return {"last_segmented_message_id": "00000000-00000000-0000-000000000001"}

    async def messages(_session_id, _after_id, limit, *, user_id):
        return [{"role": "user"}] * message_count

    async def idle(_session_id, *, user_id):
        return idle_hours

    monkeypatch.setattr(memory, "_get_cached_pipeline_state_async", state)
    monkeypatch.setattr(memory, "get_session_messages_after_id_async", messages)
    monkeypatch.setattr(memory, "_is_fence_active_async", lambda *a, **k: _false())
    monkeypatch.setattr(memory, "_get_session_idle_hours_async", idle)

    async def run(message_count_value, idle_hours_value):
        nonlocal message_count, idle_hours
        message_count, idle_hours = message_count_value, idle_hours_value
        return await memory.should_trigger_segmentation_async("s", 0, "u")

    async def _false():
        return False

    message_count = 19
    idle_hours = 4
    assert await run(19, 4) == (False, 19)
    assert await run(20, 2) == (False, 20)
    assert await run(20, 3) == (True, 20)
    assert await run(40, 0) == (True, 40)


@pytest.mark.asyncio
async def test_enqueue_deduplicates_session(monkeypatch):
    from app.memory import memory

    memory._queued_sessions.clear()
    memory._worker_task = None
    created = []

    class Queue:
        async def put(self, item):
            created.append(item)

    monkeypatch.setattr(memory, "_pending_sessions", Queue())

    class RunningTask:
        def done(self):
            return False

    monkeypatch.setattr(memory, "_worker_task", RunningTask())
    assert await memory.enqueue_memory_pipeline_async("s", "u") is True
    assert await memory.enqueue_memory_pipeline_async("s", "u") is False
    memory._queued_sessions.clear()
