-- Phase 3.1 — Purge api_keys table
-- Decommission the server-side key store. All keys now live client-side
-- (LocalStorage BYOK) and are sent per-request via X-Provider-Key header.
--
-- This NULLs all key material. The table itself is NOT dropped (never-drop rule).
-- The SQL constants and facade methods remain as inert dead code.
--
-- Run after deploying the code changes that remove the DB key-read path.

BEGIN;

-- Drop NOT NULL constraint so key_value can be NULLed (additive: makes
-- the column more permissive, does not drop data or the table).
ALTER TABLE api_keys ALTER COLUMN key_value DROP NOT NULL;

-- Purge all key material — both plaintext and encrypted flags
UPDATE api_keys
SET key_value = NULL,
    key_encrypted = FALSE;

-- Verify: should be 0 non-null keys
DO $$
DECLARE remaining int;
BEGIN
  SELECT count(*) INTO remaining FROM api_keys WHERE key_value IS NOT NULL;
  IF remaining > 0 THEN
    RAISE EXCEPTION 'Purge incomplete: % keys still have non-null key_value', remaining;
  END IF;
  RAISE NOTICE 'api_keys purged: all key_value set to NULL, key_encrypted set to FALSE';
END $$;

COMMIT;
