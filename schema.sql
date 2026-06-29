
-- ============================================================
-- Supabase / PostgreSQL schema for Football Match Organizer
-- ============================================================

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id            BIGINT PRIMARY KEY,
    username      TEXT,
    name          TEXT,
    photo_url     TEXT,
    skill_level   DOUBLE PRECISION NOT NULL DEFAULT 50.0 CHECK (skill_level >= 0 AND skill_level <= 100),
    goals         INTEGER NOT NULL DEFAULT 0,
    matches_played INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Matches table
CREATE TABLE IF NOT EXISTS matches (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'finished')),
    team_a      JSONB NOT NULL DEFAULT '[]'::jsonb,
    team_b      JSONB NOT NULL DEFAULT '[]'::jsonb,
    score_a     INTEGER NOT NULL DEFAULT 0,
    score_b     INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);

-- Index for top query
CREATE INDEX IF NOT EXISTS idx_users_skill_level ON users (skill_level DESC);
CREATE INDEX IF NOT EXISTS idx_matches_status ON matches (status);

-- Helpful view for debugging
CREATE OR REPLACE VIEW v_top_players AS
    SELECT id, username, name, photo_url, skill_level, goals, matches_played
    FROM users
    ORDER BY skill_level DESC, goals DESC;
