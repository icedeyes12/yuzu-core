-- =====================================================================
-- Multi-Tenant Refactor — Phase 1 Cutover (Steps 1.4 + 1.5 + 1.6)
-- yuzu-companion · 2026-06-21
-- ---------------------------------------------------------------------
-- AUDITED LIVE STATE before this run (verified against the live DB):
--   * Steps 1.1-1.3 ALREADY APPLIED:
--       - generate_uuidv7() exists (pgcrypto present)
--       - profiles.new_id      UUID NOT NULL, unique  -- candidate PK
--       - chat_sessions.new_id UUID NOT NULL, unique  -- candidate PK
--       - chat_sessions.user_id / messages.user_id / semantic_facts.user_id
--         UUID NOT NULL, zero NULLs, all backfilled to the single tenant
--       - messages.new_session_id UUID (nullable; 494 orphans NULL — intended)
--   * Step 1.4 NOT YET APPLIED — profiles.id is still integer SERIAL PK
--   * messages_session_id_fkey DOES NOT EXIST (FK was absent pre-migration)
--   * zero FKs reference profiles / chat_sessions / messages / semantic_facts
--   * user_id indexes ALREADY EXIST (not recreated here):
--       idx_chat_sessions_user_id, idx_messages_user_id,
--       idx_messages_session_user (redundant, pre-existing), idx_semantic_facts_user_id
--
-- This transaction performs 1.4 + 1.5 + 1.6 ATOMICALLY.
-- 1.6 hard-depends on 1.4: tenant FKs reference profiles(id), which must be UUID.
--
-- *** POINT OF NO RETURN *** — the PK/FK cutover cannot be rolled back in-place.
-- Rollback = restore from the Phase 0 pg_dump. Verify that backup is restorable
-- BEFORE running this.
-- =====================================================================

BEGIN;

-- ── Pre-flight assertions: abort unless we are exactly at the 1.3 state ──
DO $$
DECLARE
  v_prof_id_type text;
  v_cs_id_type   text;
  v_prof_dups    bigint;
  v_cs_dups      bigint;
  v_uid_nulls    bigint;
  v_fn           oid;
BEGIN
  SELECT format_type(a.atttypid, a.atttypmod) INTO v_prof_id_type
  FROM pg_attribute a WHERE a.attrelid = 'profiles'::regclass AND a.attname = 'id';
  SELECT format_type(a.atttypid, a.atttypmod) INTO v_cs_id_type
  FROM pg_attribute a WHERE a.attrelid = 'chat_sessions'::regclass AND a.attname = 'id';

  IF v_prof_id_type IS NULL OR v_prof_id_type <> 'integer' THEN
    RAISE EXCEPTION 'Pre-flight FAIL: profiles.id expected integer (Step 1.4 not yet run), got %', v_prof_id_type;
  END IF;
  IF v_cs_id_type IS NULL OR v_cs_id_type <> 'integer' THEN
    RAISE EXCEPTION 'Pre-flight FAIL: chat_sessions.id expected integer (Step 1.5 not yet run), got %', v_cs_id_type;
  END IF;

  SELECT count(*) - count(DISTINCT new_id) INTO v_prof_dups FROM profiles;
  SELECT count(*) - count(DISTINCT new_id) INTO v_cs_dups   FROM chat_sessions;
  IF v_prof_dups > 0 THEN RAISE EXCEPTION 'Pre-flight FAIL: profiles.new_id not unique, % dup(s)', v_prof_dups; END IF;
  IF v_cs_dups   > 0 THEN RAISE EXCEPTION 'Pre-flight FAIL: chat_sessions.new_id not unique, % dup(s)', v_cs_dups; END IF;

  SELECT (SELECT count(*) FROM chat_sessions  WHERE user_id IS NULL)
       + (SELECT count(*) FROM messages       WHERE user_id IS NULL)
       + (SELECT count(*) FROM semantic_facts WHERE user_id IS NULL) INTO v_uid_nulls;
  IF v_uid_nulls > 0 THEN
    RAISE EXCEPTION 'Pre-flight FAIL: % NULL user_id row(s) — Step 1.3 not complete', v_uid_nulls;
  END IF;

  SELECT oid INTO v_fn FROM pg_proc WHERE proname = 'generate_uuidv7';
  IF v_fn IS NULL THEN RAISE EXCEPTION 'Pre-flight FAIL: generate_uuidv7() missing — Step 1.1 not complete'; END IF;

  RAISE NOTICE 'Pre-flight OK: at Step 1.3 state — proceeding with 1.4 + 1.5 + 1.6';
END $$;

-- =====================================================================
-- STEP 1.4 — profiles PK cutover (SERIAL integer -> UUIDv7)
-- Safe: no FK dependents on profiles.id (audited: 0 FKs reference profiles).
-- =====================================================================
ALTER TABLE profiles DROP CONSTRAINT IF EXISTS profiles_pkey;
ALTER TABLE profiles ALTER COLUMN id DROP DEFAULT;            -- drop nextval('profiles_id_seq')
ALTER TABLE profiles RENAME COLUMN id      TO legacy_int_id;
ALTER TABLE profiles RENAME COLUMN new_id  TO id;
DROP INDEX IF EXISTS profiles_new_id_uidx;                    -- avoid duplicate unique idx post-rename
ALTER TABLE profiles ADD CONSTRAINT profiles_pkey PRIMARY KEY (id);
ALTER TABLE profiles ALTER COLUMN id SET DEFAULT generate_uuidv7();
DROP SEQUENCE IF EXISTS profiles_id_seq;
-- legacy_int_id retained (never-drop rule); now a plain NOT NULL integer w/o default.

-- =====================================================================
-- STEP 1.5 — chat_sessions PK cutover + messages->chat_sessions FK rewire to UUID
-- =====================================================================
-- messages FK was already absent pre-migration (audited). Guard with IF EXISTS.
ALTER TABLE messages DROP CONSTRAINT IF EXISTS messages_session_id_fkey;

-- chat_sessions: integer PK -> UUID PK
ALTER TABLE chat_sessions DROP CONSTRAINT IF EXISTS chat_sessions_pkey;
ALTER TABLE chat_sessions ALTER COLUMN id DROP DEFAULT;       -- drop nextval('chat_sessions_id_seq')
ALTER TABLE chat_sessions RENAME COLUMN id      TO legacy_int_id;
ALTER TABLE chat_sessions RENAME COLUMN new_id  TO id;
DROP INDEX IF EXISTS idx_chat_sessions_new_id_uidx;           -- avoid duplicate unique idx post-rename
ALTER TABLE chat_sessions ADD CONSTRAINT chat_sessions_pkey PRIMARY KEY (id);
ALTER TABLE chat_sessions ALTER COLUMN id SET DEFAULT generate_uuidv7();
DROP SEQUENCE IF EXISTS chat_sessions_id_seq;

-- messages: session_id integer -> session_id uuid (rewire FK to UUID chat_sessions.id)
ALTER TABLE messages RENAME COLUMN session_id      TO legacy_session_id;
ALTER TABLE messages RENAME COLUMN new_session_id  TO session_id;
ALTER TABLE messages ADD CONSTRAINT messages_session_id_fkey
  FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE;
-- messages.session_id (uuid) stays NULLABLE: 494 orphan rows keep NULL
-- (their original integer session referenced a now-gone session). Intended.

-- =====================================================================
-- STEP 1.6 — tenant FKs (the real isolation constraint)
-- Now safe: profiles.id is UUID and matches user_id UUID on all 3 tables.
-- user_id indexes already exist (audited) — NOT recreated here.
-- =====================================================================
ALTER TABLE chat_sessions  ADD CONSTRAINT chat_sessions_user_id_fkey
  FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
ALTER TABLE messages       ADD CONSTRAINT messages_user_id_fkey
  FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
ALTER TABLE semantic_facts ADD CONSTRAINT semantic_facts_user_id_fkey
  FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;

COMMIT;

-- =====================================================================
-- POST-CUTOVER VERIFICATION (runs OUTSIDE the transaction, after COMMIT)
-- All of these must return the values noted in comments.
-- =====================================================================
-- PK/FK column types — expect: profiles.id uuid, chat_sessions.id uuid, messages.session_id uuid
SELECT 'profiles.id'         AS col, format_type(atttypid, atttypmod) AS type FROM pg_attribute WHERE attrelid = 'profiles'::regclass       AND attname = 'id'
UNION ALL SELECT 'chat_sessions.id',  format_type(atttypid, atttypmod)         FROM pg_attribute WHERE attrelid = 'chat_sessions'::regclass  AND attname = 'id'
UNION ALL SELECT 'messages.session_id', format_type(atttypid, atttypmod)       FROM pg_attribute WHERE attrelid = 'messages'::regclass      AND attname = 'session_id';

-- New FK constraints — expect 4 rows: messages_session_id_fkey + 3 *_user_id_fkey
SELECT conrelid::regclass::text AS tbl, conname, pg_get_constraintdef(oid) AS fk
FROM pg_constraint
WHERE contype = 'f'
  AND conrelid IN ('messages'::regclass, 'chat_sessions'::regclass, 'semantic_facts'::regclass)
ORDER BY tbl, conname;

-- Row counts — expect unchanged: 1 / 40 / 12924 / 2362
SELECT 'profiles' AS t, count(*) FROM profiles
UNION ALL SELECT 'chat_sessions',  count(*) FROM chat_sessions
UNION ALL SELECT 'messages',       count(*) FROM messages
UNION ALL SELECT 'semantic_facts', count(*) FROM semantic_facts;

-- Broken FK check — expect 0 (every non-null session_id has a parent chat_session)
SELECT count(*) AS broken_session_fk
FROM messages m
LEFT JOIN chat_sessions c ON m.session_id = c.id
WHERE m.session_id IS NOT NULL AND c.id IS NULL;

-- Pre-existing orphans — expect 494 (NULL session_id, kept honestly)
SELECT count(*) AS null_session_id FROM messages WHERE session_id IS NULL;
