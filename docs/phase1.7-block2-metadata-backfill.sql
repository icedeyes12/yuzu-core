-- =====================================================================
-- Phase 1.7 Block 2 — Metadata session_id backfill (int → UUID string)
-- yuzu-companion · 2026-06-21
-- ---------------------------------------------------------------------
-- Pre-state: 2026 facts have integer-format session_id in metadata
--            336 facts have NULL session_id in metadata
--            50 facts have orphaned int session_id (no matching session)
--
-- Post-state: 1976 facts → UUID string session_id
--             386 facts → NULL session_id (336 original + 50 orphaned)
--             0 facts → integer-format session_id
-- =====================================================================

BEGIN;

-- Part 1: Backfill mappable facts (int session_id → UUID string)
UPDATE semantic_facts sf
SET metadata = jsonb_set(
    sf.metadata,
    '{session_id}',
    to_jsonb(cs.id::text)
)
FROM chat_sessions cs
WHERE (sf.metadata->>'session_id') ~ '^[0-9]+$'
  AND (sf.metadata->>'session_id')::int = cs.legacy_int_id;

-- Part 2: Null out orphaned facts (int session_id with no matching session)
UPDATE semantic_facts sf
SET metadata = jsonb_set(
    sf.metadata,
    '{session_id}',
    'null'::jsonb
)
WHERE (sf.metadata->>'session_id') ~ '^[0-9]+$'
  AND NOT EXISTS (
    SELECT 1 FROM chat_sessions cs
    WHERE (sf.metadata->>'session_id')::int = cs.legacy_int_id
  );

-- Verification
SELECT
  count(*) AS total,
  count(*) FILTER (WHERE (metadata->>'session_id') ~ '^[0-9]+$') AS still_int,
  count(*) FILTER (WHERE (metadata->>'session_id') ~ '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$') AS now_uuid,
  count(*) FILTER (WHERE metadata->>'session_id' IS NULL) AS null_count
FROM semantic_facts;

COMMIT;
