from __future__ import annotations

from app.db.connection import pg_fetchall_async


class MemoryStatsService:
    @staticmethod
    async def get_stats(user_id: str) -> dict[str, object]:
        rows = await pg_fetchall_async(
            """
            SELECT
                (SELECT COUNT(*) FROM memory_nodes WHERE user_id = %s AND status = 'active' AND valid_until IS NULL) AS nodes,
                (SELECT COUNT(*) FROM memory_edges WHERE user_id = %s AND valid_until IS NULL) AS edges,
                (SELECT COUNT(*) FROM memory_evidence WHERE user_id = %s) AS evidence,
                (SELECT COUNT(*) FROM episodes WHERE user_id = %s AND archived_at IS NULL) AS episodes
            """,
            (user_id, user_id, user_id, user_id),
        )
        return rows[0] if rows else {}
