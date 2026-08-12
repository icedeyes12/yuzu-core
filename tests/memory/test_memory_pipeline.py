import pytest

from app.core.context import RequestKeyring, clear_request_keyring, set_request_keyrings
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


def test_episode_message_provenance_is_foreign_key_backed():
    schema = "\n".join(SCHEMA_DDL)
    assert "FOREIGN KEY (source_start_message_id) REFERENCES messages(id)" in schema
    assert "FOREIGN KEY (source_end_message_id) REFERENCES messages(id)" in schema
    assert "ADD CONSTRAINT episodes_source_start_message_fk" in schema
    assert "ADD CONSTRAINT episodes_source_end_message_fk" in schema
    assert "SET source_start_message_id = NULL" in schema
    assert "SET source_end_message_id = NULL" in schema


@pytest.mark.asyncio
async def test_mark_segmentation_done_advances_legacy_count_from_checkpoint(
    monkeypatch,
):
    from app.memory import memory

    updates = []

    async def state(_session_id, _user_id):
        return {"last_segmented_count": 512}

    async def update(_session_id, payload, *, user_id):
        updates.append((payload, user_id))

    monkeypatch.setattr(memory, "get_pipeline_state_async", state)
    monkeypatch.setattr(memory, "update_pipeline_state_async", update)

    await memory.mark_segmentation_done_async("session", "message", 7, user_id="user")

    assert updates[0][0]["last_segmented_count"] == 519


def test_graph_queries_are_tenant_scoped():
    assert "user_id = %s" in SQL_GRAPH_NODE_SEARCH_TEXT
    assert "user_id = %s" in SQL_GRAPH_NODE_SEARCH_VECTOR
    assert "e.user_id = %s" in SQL_GRAPH_NODE_EXPAND


def test_vector_literal():
    assert vector_literal(None) is None
    assert vector_literal([]) == "[]"
    assert vector_literal([0.1, 0.2]) == "[0.1,0.2]"


def test_adaptive_batches_respect_token_budget():
    from app.memory.extractor import build_adaptive_batches, estimate_message_tokens

    messages = [{"role": "user", "content": "x" * 40}] * 5
    batches = build_adaptive_batches(messages, token_budget=20, max_messages=100)
    assert [len(batch) for batch in batches] == [1, 1, 1, 1, 1]
    assert all(
        estimate_message_tokens(message) <= 20 for batch in batches for message in batch
    )


def test_adaptive_batches_truncate_oversized_message_without_mutating_source():
    from app.memory.extractor import build_adaptive_batches, estimate_message_tokens

    original = {"role": "user", "content": "x" * 200}
    batches = build_adaptive_batches([original], token_budget=20)

    assert len(batches) == 1
    assert estimate_message_tokens(batches[0][0]) <= 20
    assert original["content"] == "x" * 200


def test_embedding_response_is_sorted_by_index():
    from app.memory.embedder import _parse_embedding_data

    vector = [0.0] * 1536
    result = _parse_embedding_data(
        [{"index": 1, "embedding": vector}, {"index": 0, "embedding": vector}],
        2,
    )

    assert len(result) == 2


def test_embedding_response_count_mismatch_is_rejected():
    from app.memory.embedder import _parse_embedding_data

    try:
        _parse_embedding_data([], 1)
    except ValueError as exc:
        assert "count mismatch" in str(exc)
    else:
        raise AssertionError("expected embedding count mismatch")


def test_memory_cursor_query_counts_only_conversational_messages():
    from app.db.queries import SQL_MESSAGE_SELECT_AFTER_ID

    assert "role IN ('user', 'assistant')" in SQL_MESSAGE_SELECT_AFTER_ID
    assert "id > %s" in SQL_MESSAGE_SELECT_AFTER_ID
    assert "ORDER BY id ASC" in SQL_MESSAGE_SELECT_AFTER_ID


def test_message_cursor_contract_uses_uuidv7_ids():
    from app.db.queries import SCHEMA_DDL

    schema = "\n".join(SCHEMA_DDL)
    assert "CREATE OR REPLACE FUNCTION generate_uuidv7()" in schema
    assert "id UUID NOT NULL DEFAULT generate_uuidv7() PRIMARY KEY" in schema


@pytest.mark.asyncio
async def test_legacy_count_checkpoint_reads_beyond_fetch_cap(monkeypatch):
    from app.memory import memory

    calls = []

    async def messages(
        session_id,
        limit=100,
        order="ASC",
        *,
        user_id,
        offset=0,
        conversational_only=False,
    ):
        calls.append(
            {
                "session_id": session_id,
                "limit": limit,
                "order": order,
                "user_id": user_id,
                "offset": offset,
                "conversational_only": conversational_only,
            }
        )
        start = offset
        stop = min(offset + (limit or 700), 700)
        return [{"id": index, "role": "user"} for index in range(start, stop)]

    monkeypatch.setattr(memory, "get_session_messages_async", messages)

    result = await memory._get_messages_after_count_async("session", 512, "user")

    assert len(result) == 188
    assert calls == [
        {
            "session_id": "session",
            "limit": memory.MESSAGE_FETCH_LIMIT,
            "order": "ASC",
            "user_id": "user",
            "offset": 512,
            "conversational_only": True,
        }
    ]


def test_memory_disabled_without_configured_provider():
    clear_request_keyring()
    from app.core.byok import YUZU_PORTAL, get_provider_key

    assert get_provider_key(YUZU_PORTAL) is None


def test_memory_requires_yuzu_portal_key():
    set_request_keyrings({"custom": RequestKeyring(provider="custom", key="secret")})
    try:
        from app.core.byok import YUZU_PORTAL, get_provider_key

        assert get_provider_key(YUZU_PORTAL) is None
    finally:
        clear_request_keyring()


def test_memory_key_is_independent_of_active_conversation_provider():
    from app.core.byok import YUZU_PORTAL, get_provider_key

    set_request_keyrings(
        {
            "openrouter": RequestKeyring(provider="openrouter", key="chat-key"),
            YUZU_PORTAL: RequestKeyring(provider=YUZU_PORTAL, key="portal-key"),
        }
    )
    try:
        assert get_provider_key(YUZU_PORTAL) == "portal-key"
    finally:
        clear_request_keyring()


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
async def test_batch_embedding_request(monkeypatch):
    from app.memory import memory

    requested = []

    async def embed(texts, **kwargs):
        requested.append(texts)
        return [[0.1] for _ in texts]

    monkeypatch.setattr(memory, "embed_texts_async", embed)
    result = await memory.embed_texts_async(["episode", "fact"])
    assert requested == [["episode", "fact"]]
    assert len(result) == 2


@pytest.mark.asyncio
async def test_retry_helper_preserves_progress_on_failure(monkeypatch):
    from app.memory import memory

    calls = []

    async def fail(_messages, profile=None):
        calls.append(1)
        raise RuntimeError("overflow")

    monkeypatch.setattr(memory, "extract_memory_batch_async", fail)
    extracted, processed, retries = await memory._extract_with_retries_async(
        [{"role": "user", "content": "x"}] * 4
    )
    assert extracted is None
    assert processed
    assert retries == memory.MAX_EXTRACTION_RETRIES
    assert len(calls) == memory.MAX_EXTRACTION_RETRIES


@pytest.mark.asyncio
async def test_consolidation_archives_only_same_relation_overlap(monkeypatch):
    from app.memory.graph import GraphMemoryRepository

    async def candidates(**kwargs):
        return [
            {"id": "old", "content": "Bas likes blue tea"},
            {"id": "conflict", "content": "Bas likes coffee"},
        ]

    archived = []

    async def archive(**kwargs):
        archived.append(kwargs["node_id"])
        return True

    monkeypatch.setattr(GraphMemoryRepository, "find_similar_active_nodes", candidates)
    monkeypatch.setattr(GraphMemoryRepository, "archive_node", archive)
    result = await GraphMemoryRepository.consolidate_node(
        user_id="u",
        node_id="new",
        node_type="fact",
        content="Bas likes blue tea",
    )
    assert result == {"candidates": 2, "archived": 1}
    assert archived == ["old"]


@pytest.mark.asyncio
async def test_consolidation_requires_exact_normalized_target(monkeypatch):
    from app.memory.graph import GraphMemoryRepository

    async def candidates(**kwargs):
        return [
            {"id": "negation", "content": "Bas likes not blue tea"},
            {"id": "qualifier", "content": "Bas likes blue tea sometimes"},
            {"id": "reordered", "content": "Bas likes tea blue"},
            {"id": "same", "content": "Bas likes blue tea"},
        ]

    archived = []

    async def archive(**kwargs):
        archived.append(kwargs["node_id"])
        return True

    monkeypatch.setattr(GraphMemoryRepository, "find_similar_active_nodes", candidates)
    monkeypatch.setattr(GraphMemoryRepository, "archive_node", archive)
    result = await GraphMemoryRepository.consolidate_node(
        user_id="u",
        node_id="new",
        node_type="fact",
        content="Bas likes blue tea",
    )

    assert result == {"candidates": 4, "archived": 1}
    assert archived == ["same"]


@pytest.mark.asyncio
async def test_enqueue_skips_when_memory_disabled(monkeypatch):
    from app.memory import memory

    async def profile(_user_id):
        return {"providers_config": {"memory_provider": "missing"}}

    monkeypatch.setattr(memory.Database, "get_profile", profile)
    assert await memory.trigger_memory_pipeline_async("s", 40, "u") is False


@pytest.mark.asyncio
async def test_enqueue_deduplicates_session(monkeypatch):
    from app.memory import memory

    async def profile(_user_id):
        return {}

    monkeypatch.setattr(memory.Database, "get_profile", profile)
    monkeypatch.setattr(
        memory,
        "get_provider_key",
        lambda provider: "portal-key" if provider == "yuzu_portal" else None,
    )
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


@pytest.mark.asyncio
async def test_recover_memory_pipeline_requeues_persisted_fence(monkeypatch):
    from app.memory import memory

    monkeypatch.setattr(memory, "get_provider_key", lambda _provider: "portal-key")
    monkeypatch.setattr(
        memory,
        "get_pipeline_state_async",
        lambda _session_id, _user_id: _state(),
    )
    monkeypatch.setattr(
        memory,
        "get_session_messages_after_id_async",
        lambda *_args, **_kwargs: _messages(),
    )
    queued = []

    async def enqueue(session_id, user_id):
        queued.append((session_id, user_id))
        return True

    monkeypatch.setattr(memory, "enqueue_memory_pipeline_async", enqueue)

    async def _state():
        return {"in_progress_fence_count": 40, "last_segmented_message_id": "cursor"}

    async def _messages():
        return [{"role": "user", "id": "next"}]

    assert await memory.recover_memory_pipeline_async("s", "u") is True
    assert queued == [("s", "u")]
