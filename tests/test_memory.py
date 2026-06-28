
from app.memory.db_memory_queries import (
    normalize_vector,
    vector_literal,
    build_metadata_conditions,
    build_search_similar_query,
    build_search_trgm_query,
    build_search_tsv_query,
    build_facts_by_session_query,
    build_count_query,
    build_update_last_accessed_query,
    FACT_TYPE_STATIC,
    FACT_TYPE_DYNAMIC,
    EMBEDDING_DIM,
)


class TestVectorHelpers:
    """Tests for vector normalization and literal rendering."""

    def test_normalize_vector_empty(self):
        """Empty list returns empty."""
        result = normalize_vector([])
        assert result == []

    def test_normalize_vector_none(self):
        """None returns empty list."""
        result = normalize_vector(None)
        assert result == []

    def test_normalize_vector_unit(self):
        """Already unit vector stays unit."""
        vec = [1.0, 0.0, 0.0]
        result = normalize_vector(vec)
        assert result == [1.0, 0.0, 0.0]

    def test_normalize_vector_scales(self):
        """Non-unit vector gets scaled to unit length."""
        vec = [3.0, 4.0]  # magnitude 5
        result = normalize_vector(vec)
        assert len(result) == 2
        # Check magnitude is 1
        mag = sum(x * x for x in result) ** 0.5
        assert abs(mag - 1.0) < 0.0001

    def test_vector_literal_none(self):
        """None input returns None."""
        result = vector_literal(None)
        assert result is None

    def test_vector_literal_renders(self):
        """List renders as bracketed CSV."""
        vec = [0.1, 0.2, 0.3]
        result = vector_literal(vec)
        assert result == "[0.1,0.2,0.3]"

    def test_vector_literal_empty(self):
        """Empty list renders as empty brackets."""
        result = vector_literal([])
        assert result == "[]"


class TestMetadataConditions:
    """Tests for WHERE clause builder."""

    def test_no_conditions(self):
        """With only user_id, returns just the tenant scope condition."""
        conditions, params = build_metadata_conditions(user_id="uid")
        assert conditions == ["user_id = %s"]
        assert params == ["uid"]

    def test_session_id_only(self):
        """Session ID adds one condition."""
        conditions, params = build_metadata_conditions(user_id="uid", session_id=42)
        assert len(conditions) == 2
        assert "(metadata->>'session_id') = %s::text" in conditions
        assert "uid" in params and 42 in params

    def test_fact_type_only(self):
        """Fact type adds one condition."""
        conditions, params = build_metadata_conditions(
            user_id="uid", fact_type="static"
        )
        assert len(conditions) == 2
        assert "fact_type = %s" in conditions
        assert "uid" in params and "static" in params

    def test_category_only(self):
        """Category adds one condition."""
        conditions, params = build_metadata_conditions(
            user_id="uid", category="Preference"
        )
        assert len(conditions) == 2
        assert "(metadata->>'category') = %s" in conditions
        assert "uid" in params and "Preference" in params

    def test_all_filters(self):
        """All filters combined."""
        conditions, params = build_metadata_conditions(
            user_id="uid",
            session_id=1,
            fact_type="dynamic",
            category="Identity",
            metadata_filter={"source": "test"},
        )
        assert (
            len(conditions) == 5
        )  # user_id + session + fact_type + category + metadata(key,val)
        assert len(params) == 6  # uid + session, fact_type, category, key, val


class TestQueryBuilders:
    """Tests for SQL query builders."""

    def test_build_search_similar_query_basic(self):
        """Basic vector search query."""
        vec_lit = "[0.1,0.2,0.3]"
        query = build_search_similar_query(vec_lit, [])
        assert "embedding IS NOT NULL" in query
        assert vec_lit in query
        assert "embedding <=" in query or "embedding <" in query

    def test_build_search_similar_query_with_conditions(self):
        """Vector search with extra conditions."""
        vec_lit = "[0.1,0.2]"
        query = build_search_similar_query(vec_lit, ["fact_type = %s"])
        assert "fact_type = %s" in query

    def test_build_search_trgm_query(self):
        """Trigram search query."""
        query = build_search_trgm_query([])
        assert "similarity(content, %s)" in query
        assert "invalid_at IS NULL" in query

    def test_build_search_tsv_query(self):
        """Full-text search query."""
        query = build_search_tsv_query([])
        assert "ts_rank" in query
        assert "plainto_tsquery" in query

    def test_build_facts_by_session_query_empty(self):
        """Empty conditions defaults to dynamic."""
        query = build_facts_by_session_query([], default_dynamic=True)
        assert "fact_type = 'dynamic'" in query

    def test_build_facts_by_session_query_with_conditions(self):
        """With conditions uses WHERE."""
        query = build_facts_by_session_query(["session_id = 1"])
        assert "WHERE session_id = 1" in query

    def test_build_count_query_empty(self):
        """Count without conditions."""
        query = build_count_query([])
        assert "SELECT COUNT(*) AS cnt FROM semantic_facts" in query
        assert "WHERE" not in query

    def test_build_count_query_with_conditions(self):
        """Count with conditions."""
        query = build_count_query(["fact_type = %s"])
        assert "WHERE fact_type = %s" in query

    def test_build_update_last_accessed_query(self):
        """Update query for multiple IDs."""
        query = build_update_last_accessed_query(3)
        assert "UPDATE semantic_facts SET last_accessed=%s" in query
        assert "id IN (%s,%s,%s)" in query


class TestConstants:
    """Tests for exported constants."""

    def test_fact_type_static(self):
        assert FACT_TYPE_STATIC == "static"

    def test_fact_type_dynamic(self):
        assert FACT_TYPE_DYNAMIC == "dynamic"

    def test_embedding_dim(self):
        assert EMBEDDING_DIM == 4096
