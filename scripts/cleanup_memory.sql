-- ============================================================================
-- Memory System Cleanup SQL
-- Run with: psql yuzuki -f scripts/cleanup_memory.sql
-- Or from Python via subprocess
-- ============================================================================

-- 1. Remove empty segments (content is NULL or < 5 chars)
-- These are LLM-generated summaries; empty means no summary was produced
DELETE FROM semantic_facts
WHERE fact_type = 'dynamic'
  AND metadata->>'source_table' = 'conversation_segments'
  AND (content IS NULL OR LENGTH(content) < 5);

-- 2. Remove noisy garbage segments (common patterns from broken extraction)
-- These are clearly not useful conversation summaries
DELETE FROM semantic_facts
WHERE fact_type = 'dynamic'
  AND metadata->>'source_table' = 'conversation_segments'
  AND content IN (
    ', kamu.',
    ', kamu.️',
    ', kamu.',
    ', kamu.',
    '...'
  );

-- 3. Remove stale episodic memories (very old, low importance)
-- These are from the old system and have been superseded
DELETE FROM semantic_facts
WHERE fact_type = 'dynamic'
  AND metadata->>'source_table' = 'episodic_memories'
  AND invalid_at IS NULL
  AND created_at < NOW() - INTERVAL '7 days'
  AND (
    metadata->>'importance' IS NULL
    OR CAST(metadata->>'importance' AS FLOAT) < 0.3
  );

-- 4. Remove exact-duplicate static facts (keep newest/highest id)
DELETE FROM semantic_facts a
WHERE a.invalid_at IS NULL
  AND a.fact_type = 'static'
  AND EXISTS (
    SELECT 1 FROM semantic_facts b
    WHERE b.fact_type = a.fact_type
      AND b.content = a.content
      AND b.invalid_at IS NULL
      AND b.id > a.id
  );

-- 5. Soft-delete duplicate static facts (near-duplicate content, keep best)
-- Keeps the one with highest confidence+importance, or newest if tied
DELETE FROM semantic_facts a
WHERE a.invalid_at IS NULL
  AND a.fact_type = 'static'
  AND (
    -- Has a better sibling (higher combined score)
    EXISTS (
      SELECT 1 FROM semantic_facts b
      WHERE b.fact_type = a.fact_type
        AND b.content % a.content  -- pg_trgm similarity
        AND b.content <> a.content
        AND b.invalid_at IS NULL
        AND (
          COALESCE((b.metadata->>'confidence')::float, 0.5) + COALESCE((b.metadata->>'importance')::float, 0.5)
          > COALESCE((a.metadata->>'confidence')::float, 0.5) + COALESCE((a.metadata->>'importance')::float, 0.5)
        )
    )
    -- OR is very low quality (importance < 0.3 and confidence < 0.5)
    OR (
      COALESCE((a.metadata->>'importance')::float, 0.5) < 0.3
      AND COALESCE((a.metadata->>'confidence')::float, 0.5) < 0.5
    )
  );

-- 6. Show summary after cleanup
SELECT
  fact_type,
  metadata->>'source_table' AS source,
  COUNT(*) AS total,
  COUNT(*) FILTER (WHERE invalid_at IS NULL) AS active,
  COUNT(*) FILTER (WHERE invalid_at IS NOT NULL) AS soft_deleted
FROM semantic_facts
GROUP BY fact_type, metadata->>'source_table'
ORDER BY fact_type, source;

-- ============================================================================
-- POST-CLEANUP: Remove garbage with "No summary" pattern and short content
-- Run AFTER the above cleanup
-- ============================================================================
DELETE FROM semantic_facts
WHERE invalid_at IS NULL
  AND (
    -- "No summary" pattern (case-insensitive via LOWER)
    LOWER(content) LIKE '%no summary%'
    -- Short garbage segments (< 5 chars, not real content)
    OR (LENGTH(content) < 5 AND fact_type = 'dynamic')
  );
