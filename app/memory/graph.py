from __future__ import annotations

from datetime import datetime
from typing import Any

from app.db.connection import AsyncPgSession, pg_fetchall_async, pg_fetchone_async
from app.db.queries import (
    SQL_GRAPH_EDGE_UPSERT,
    SQL_GRAPH_EPISODE_INSERT,
    SQL_GRAPH_EVIDENCE_INSERT,
    SQL_GRAPH_EVIDENCE_REASSIGN,
    SQL_GRAPH_NODE_ARCHIVE,
    SQL_GRAPH_NODE_BY_CONTENT,
    SQL_GRAPH_NODE_EXPAND,
    SQL_GRAPH_NODE_INSERT,
    SQL_GRAPH_NODE_LIST,
    SQL_GRAPH_NODE_PROVENANCE,
    SQL_GRAPH_NODE_SEARCH_TEXT,
    SQL_GRAPH_NODE_SEARCH_VECTOR,
    SQL_GRAPH_NODE_SIMILAR_ACTIVE,
)


def vector_literal(vector: list[float] | None) -> str | None:
    if vector is None:
        return None
    return "[" + ",".join(str(float(value)) for value in vector) + "]"


_GRAPH_EMBEDDING_DIMENSIONS = 1536


class GraphMemoryRepository:
    """Persistence and bounded retrieval for graph-backed inferred memory."""

    @staticmethod
    async def create_episode(
        *,
        user_id: str,
        session_id: str,
        title: str,
        summary: str,
        embedding: list[float] | None,
        importance: float,
        source_start_message_id: str | None,
        source_end_message_id: str | None,
    ) -> dict[str, Any] | None:
        return await _returning(
            SQL_GRAPH_EPISODE_INSERT,
            (
                user_id,
                session_id,
                title,
                summary,
                vector_literal(embedding),
                importance,
                source_start_message_id,
                source_end_message_id,
            ),
        )

    @staticmethod
    async def get_or_create_node(
        *,
        user_id: str,
        node_type: str,
        content: str,
        embedding: list[float] | None,
        confidence: float,
        importance: float,
        embedding_model: str | None,
        embedding_dimensions: int | None,
        supersedes_node_id: str | None = None,
    ) -> dict[str, Any] | None:
        existing = await pg_fetchone_async(
            SQL_GRAPH_NODE_BY_CONTENT, (user_id, content)
        )
        if existing:
            if embedding is not None:
                existing_embedding = existing.get("embedding")
                if existing_embedding is None:
                    return await _update_node_embedding(
                        str(existing["id"]),
                        user_id,
                        embedding,
                        embedding_model,
                        embedding_dimensions,
                    )
            return existing
        return await _returning(
            SQL_GRAPH_NODE_INSERT,
            (
                user_id,
                node_type,
                content,
                vector_literal(embedding),
                confidence,
                importance,
                datetime.now(),
                supersedes_node_id,
                embedding_model,
                embedding_dimensions,
            ),
        )

    @staticmethod
    async def find_similar_active_nodes(
        *,
        user_id: str,
        node_id: str,
        node_type: str,
        content: str,
        threshold: float = 0.92,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        return await pg_fetchall_async(
            SQL_GRAPH_NODE_SIMILAR_ACTIVE,
            (content, user_id, node_id, node_type, content, threshold, limit),
        )

    @staticmethod
    async def consolidate_node(
        *,
        user_id: str,
        node_id: str,
        node_type: str,
        content: str,
        threshold: float = 0.92,
    ) -> dict[str, int]:
        """Archive only same-relation overlaps; preserve evidence on canonical node."""
        parts = content.split(" ", 2)
        if len(parts) != 3:
            return {"candidates": 0, "archived": 0}
        entity, relation, target = parts
        normalized_entity = entity.lower()
        normalized_relation = relation.lower()
        candidates = await GraphMemoryRepository.find_similar_active_nodes(
            user_id=user_id,
            node_id=node_id,
            node_type=node_type,
            content=content,
            threshold=threshold,
        )
        archived = 0
        for candidate in candidates:
            candidate_parts = str(candidate.get("content", "")).split(" ", 2)
            if (
                len(candidate_parts) != 3
                or candidate_parts[0].lower() != normalized_entity
                or candidate_parts[1].lower() != normalized_relation
            ):
                continue
            # If candidate matches same entity-relation, supersede the older candidate node
            if await GraphMemoryRepository.archive_node(
                user_id=user_id, node_id=str(candidate["id"]), canonical_node_id=node_id
            ):
                archived += 1
        return {"candidates": len(candidates), "archived": archived}

    @staticmethod
    async def list_active_nodes(
        *, user_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        return await pg_fetchall_async(SQL_GRAPH_NODE_LIST, (user_id, limit))

    @staticmethod
    async def delete_node_soft(*, user_id: str, node_id: str) -> bool:
        query = """
        UPDATE memory_nodes
        SET status = 'deleted', valid_until = NOW(), updated_at = NOW()
        WHERE id = %s AND user_id = %s AND status = 'active'
        RETURNING id
        """
        row = await pg_fetchone_async(query, (node_id, user_id))
        return row is not None

    @staticmethod
    async def archive_node(
        *, user_id: str, node_id: str, canonical_node_id: str
    ) -> bool:
        async with AsyncPgSession() as session:
            archived = await session.execute_returning(
                SQL_GRAPH_NODE_ARCHIVE,
                (
                    user_id,
                    canonical_node_id,
                    node_id,
                    canonical_node_id,
                    node_id,
                    user_id,
                    canonical_node_id,
                    node_id,
                ),
            )
            if not archived:
                return False
            await session.execute(
                SQL_GRAPH_EVIDENCE_REASSIGN,
                (canonical_node_id, user_id, node_id),
            )
            return True

    @staticmethod
    async def add_edge(
        *,
        user_id: str,
        from_node_id: str,
        to_node_id: str,
        edge_type: str,
        confidence: float,
    ) -> dict[str, Any] | None:
        return await _returning(
            SQL_GRAPH_EDGE_UPSERT,
            (user_id, from_node_id, to_node_id, edge_type, confidence),
        )

    @staticmethod
    async def add_evidence(
        *,
        user_id: str,
        node_id: str,
        episode_id: str | None,
        message_ids: list[str | int],
        evidence_kind: str = "extraction",
    ) -> int:
        inserted = 0
        async with AsyncPgSession() as session:
            for message_id in message_ids:
                row = await session.execute_returning(
                    SQL_GRAPH_EVIDENCE_INSERT,
                    (
                        user_id,
                        node_id,
                        None,
                        episode_id,
                        message_id,
                        evidence_kind,
                        None,
                    ),
                )
                inserted += int(row is not None)
        return inserted

    @staticmethod
    async def search_nodes(
        *, user_id: str, query: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        if not query.strip():
            return await pg_fetchall_async(SQL_GRAPH_NODE_LIST, (user_id, limit))
        return await pg_fetchall_async(
            SQL_GRAPH_NODE_SEARCH_TEXT, (query, user_id, query, limit)
        )

    @staticmethod
    async def get_node_provenance(
        *, user_id: str, node_id: str
    ) -> list[dict[str, Any]]:
        return await pg_fetchall_async(SQL_GRAPH_NODE_PROVENANCE, (user_id, node_id))

    @staticmethod
    async def search_nodes_vector(
        *,
        user_id: str,
        embedding: list[float],
        min_score: float = 0.70,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        return await pg_fetchall_async(
            SQL_GRAPH_NODE_SEARCH_VECTOR,
            (
                vector_literal(embedding),
                user_id,
                _GRAPH_EMBEDDING_DIMENSIONS,
                vector_literal(embedding),
                min_score,
                limit,
            ),
        )

    @staticmethod
    async def expand_nodes(
        *, user_id: str, node_id: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        return await pg_fetchall_async(
            SQL_GRAPH_NODE_EXPAND,
            (node_id, user_id, node_id, node_id, user_id, limit),
        )


async def _update_node_embedding(
    node_id: str,
    user_id: str,
    embedding: list[float],
    embedding_model: str | None,
    embedding_dimensions: int | None,
) -> dict[str, Any] | None:
    query = """
    UPDATE memory_nodes
    SET embedding = %s::vector, embedding_model = %s,
        embedding_dimensions = %s, updated_at = NOW()
    WHERE id = %s AND user_id = %s
    RETURNING id, user_id, node_type, content, embedding, confidence, importance, status,
              valid_from, valid_until, supersedes_node_id, embedding_model,
              embedding_dimensions, created_at, updated_at, last_accessed_at
    """
    return await _returning(
        query,
        (
            vector_literal(embedding),
            embedding_model,
            embedding_dimensions,
            node_id,
            user_id,
        ),
    )


async def list_evidence(
    *, user_id: str, node_id: str, limit: int = 20
) -> list[dict[str, Any]]:
    return await pg_fetchall_async(
        """
        SELECT e.id, e.node_id, e.edge_id, e.episode_id, e.message_id,
               e.evidence_kind, e.excerpt_hash, e.observed_at, e.created_at,
               ep.title AS episode_title, ep.summary AS episode_summary
        FROM memory_evidence e
        LEFT JOIN episodes ep ON ep.id = e.episode_id AND ep.user_id = e.user_id
        WHERE e.user_id = %s AND e.node_id = %s
        ORDER BY e.created_at DESC
        LIMIT %s
        """,
        (user_id, node_id, limit),
    )


async def _returning(query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    async with AsyncPgSession() as session:
        return await session.execute_returning(query, params)


__all__ = ["GraphMemoryRepository"]
