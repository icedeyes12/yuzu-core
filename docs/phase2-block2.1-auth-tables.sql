-- =====================================================================
-- Multi-Tenant Refactor — Phase 2, Block 2.1 (Auth Tables DDL)
-- yuzu-companion · 2026-06-22
-- ---------------------------------------------------------------------
-- Adds two new tables for OAuth2 + server-side session auth:
--   * user_identities  — OAuth provider linkage (Google sub / GitHub id)
--   * user_sessions    — opaque server-side session tokens
--
-- Both reference profiles(id) UUID PK via ON DELETE CASCADE FK.
--
-- Design decisions:
--   * user_identities.id uses generate_uuidv7() (not gen_random_uuid())
--     for schema-wide consistency — time-ordered, lexicographically sortable.
--   * Inline UNIQUE(provider, provider_sub) constraint creates an implicit
--     unique index; no separate CREATE UNIQUE INDEX needed (avoids duplicate).
--   * user_sessions.token is TEXT (opaque 32-byte urlsafe random), NOT UUID —
--     server-side sessions are revocable, unlike stateless JWTs.
--
-- Idempotent: safe to run multiple times (IF NOT EXISTS on all objects).
-- =====================================================================

BEGIN;

-- ── Pre-flight: abort if profiles.id is not UUID (Phase 1 must be complete) ──
DO $$
DECLARE
  v_prof_id_type text;
BEGIN
  SELECT format_type(a.atttypid, a.atttypmod) INTO v_prof_id_type
  FROM pg_attribute a
  WHERE a.attrelid = 'profiles'::regclass AND a.attname = 'id';

  IF v_prof_id_type IS NULL OR v_prof_id_type <> 'uuid' THEN
    RAISE EXCEPTION 'Pre-flight FAIL: profiles.id expected uuid (Phase 1 incomplete), got %', v_prof_id_type;
  END IF;
END $$;

-- ── Table: user_identities (OAuth linkage) ──
CREATE TABLE IF NOT EXISTS user_identities (
    id UUID NOT NULL DEFAULT generate_uuidv7() PRIMARY KEY,
    user_id UUID NOT NULL,
    provider VARCHAR(32) NOT NULL,
    provider_sub TEXT NOT NULL,
    email TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (provider, provider_sub),
    FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
);

-- ── Table: user_sessions (server-side session tokens) ──
CREATE TABLE IF NOT EXISTS user_sessions (
    token TEXT PRIMARY KEY,
    user_id UUID NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL,
    revoked_at TIMESTAMP DEFAULT NULL,
    FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
);

-- ── Indexes ──
CREATE INDEX IF NOT EXISTS idx_user_identities_user_id ON user_identities(user_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_user ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_expires ON user_sessions(expires_at);

-- ── Post-flight verification ──
DO $$
DECLARE
  v_uid_count int;
  v_us_count int;
BEGIN
  SELECT count(*) INTO v_uid_count FROM information_schema.tables
  WHERE table_name = 'user_identities' AND table_schema = 'public';
  SELECT count(*) INTO v_us_count FROM information_schema.tables
  WHERE table_name = 'user_sessions' AND table_schema = 'public';

  IF v_uid_count <> 1 THEN
    RAISE EXCEPTION 'Post-flight FAIL: user_identities table not created';
  END IF;
  IF v_us_count <> 1 THEN
    RAISE EXCEPTION 'Post-flight FAIL: user_sessions table not created';
  END IF;
END $$;

COMMIT;
