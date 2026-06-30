
-- ============================================================
-- Supabase / PostgreSQL schema для Football Match Organizer
— Полная схема со всеми новыми таблицами и полями
-- ============================================================

-- Таблица пользователей (расширенная)
CREATE TABLE IF NOT EXISTS users (
    id              BIGINT PRIMARY KEY,
    username        TEXT,
    name            TEXT,
    photo_url       TEXT,
    position        TEXT NOT NULL DEFAULT 'unknown' CHECK (position IN ('Вратарь', 'Защитник', 'Нападающий', 'unknown')),
    skill_level     DOUBLE PRECISION NOT NULL DEFAULT 50.0 CHECK (skill_level >= 0 AND skill_level <= 100),
    goals           INTEGER NOT NULL DEFAULT 0,
    assists         INTEGER NOT NULL DEFAULT 0,
    matches_played  INTEGER NOT NULL DEFAULT 0,
    wins            INTEGER NOT NULL DEFAULT 0,
    losses          INTEGER NOT NULL DEFAULT 0,
    draws           INTEGER NOT NULL DEFAULT 0,
    mvp_count       INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Таблица матчей (расширенная)
CREATE TABLE IF NOT EXISTS matches (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'finished', 'scheduled')),
    team_a          JSONB NOT NULL DEFAULT '[]'::jsonb,
    team_b          JSONB NOT NULL DEFAULT '[]'::jsonb,
    score_a         INTEGER NOT NULL DEFAULT 0,
    score_b         INTEGER NOT NULL DEFAULT 0,
    scheduled_at    TIMESTAMPTZ,
    location        TEXT,
    started_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ
);

-- Таблица регистрации на матч (предварительная запись)
CREATE TABLE IF NOT EXISTS match_registrations (
    match_id    UUID NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status      TEXT NOT NULL DEFAULT 'confirmed' CHECK (status IN ('confirmed', 'cancelled')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (match_id, user_id)
);

-- Таблица голосования за MVP
CREATE TABLE IF NOT EXISTS mvp_votes (
    match_id        UUID NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    voter_id        BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    candidate_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (match_id, voter_id),
    CHECK (voter_id <> candidate_id)
);

-- Таблица достижений
CREATE TABLE IF NOT EXISTS user_achievements (
    user_id             BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    achievement_code    TEXT NOT NULL,
    unlocked_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, achievement_code)
);

-- Индексы для производительности
CREATE INDEX IF NOT EXISTS idx_users_skill_level ON users (skill_level DESC);
CREATE INDEX IF NOT EXISTS idx_users_position ON users (position);
CREATE INDEX IF NOT EXISTS idx_matches_status ON matches (status);
CREATE INDEX IF NOT EXISTS idx_matches_scheduled_at ON matches (scheduled_at) WHERE scheduled_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_match_registrations_match_id ON match_registrations (match_id);
CREATE INDEX IF NOT EXISTS idx_mvp_votes_match_id ON mvp_votes (match_id);
CREATE INDEX IF NOT EXISTS idx_user_achievements_user_id ON user_achievements (user_id);

-- Вьюшка для топ-10 игроков
CREATE OR REPLACE VIEW v_top_players AS
    SELECT id, username, name, photo_url, position, skill_level, goals, assists, matches_played, wins, losses, draws, mvp_count
    FROM users
    ORDER BY skill_level DESC, goals DESC;
