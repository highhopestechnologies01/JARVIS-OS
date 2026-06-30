-- ============================================================
-- JARVIS OS — PostgreSQL Initialization
-- Runs once on first container start
-- ============================================================

-- Create n8n database (n8n needs its own DB)
CREATE DATABASE n8n;

-- Connect to jarvis database
\c jarvis;

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- For text search on memories

-- ============================================================
-- HERMES SCHEMA
-- ============================================================

-- Memory: long-term context store
CREATE TABLE IF NOT EXISTS memories (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    type        VARCHAR(50) NOT NULL,       -- 'person', 'project', 'event', 'fact', 'preference'
    topic       VARCHAR(200),               -- Short label for search
    content     TEXT NOT NULL,              -- The actual memory
    metadata    JSONB DEFAULT '{}',         -- Flexible extra data
    importance  INTEGER DEFAULT 5,          -- 1-10 scale
    source      VARCHAR(100),               -- Where this memory came from
    expires_at  TIMESTAMPTZ,               -- NULL = permanent
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_memories_type ON memories(type);
CREATE INDEX idx_memories_topic ON memories USING gin(topic gin_trgm_ops);
CREATE INDEX idx_memories_content ON memories USING gin(content gin_trgm_ops);
CREATE INDEX idx_memories_created ON memories(created_at DESC);

-- Scheduled tasks
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        VARCHAR(200) NOT NULL UNIQUE,
    description TEXT,
    cron_expr   VARCHAR(100) NOT NULL,       -- Standard cron: '0 8 * * *'
    handler     VARCHAR(200) NOT NULL,       -- Python function path
    args        JSONB DEFAULT '{}',
    enabled     BOOLEAN DEFAULT TRUE,
    last_run    TIMESTAMPTZ,
    last_status VARCHAR(20),                 -- 'success', 'error', 'running'
    last_error  TEXT,
    next_run    TIMESTAMPTZ,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Briefings: daily executive summaries
CREATE TABLE IF NOT EXISTS briefings (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    date        DATE NOT NULL UNIQUE,
    content     TEXT NOT NULL,              -- Full briefing markdown
    summary     TEXT,                       -- One paragraph summary
    sources     JSONB DEFAULT '[]',         -- What data was used
    status      VARCHAR(20) DEFAULT 'draft', -- 'draft', 'delivered', 'error'
    delivered_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_briefings_date ON briefings(date DESC);

-- Events: audit log of all Hermes actions
CREATE TABLE IF NOT EXISTS events (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    type        VARCHAR(100) NOT NULL,       -- 'briefing.generated', 'memory.stored', etc.
    source      VARCHAR(100),               -- Which module triggered it
    payload     JSONB DEFAULT '{}',
    status      VARCHAR(20) DEFAULT 'ok',   -- 'ok', 'error', 'warning'
    error       TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_events_type ON events(type);
CREATE INDEX idx_events_created ON events(created_at DESC);

-- Notifications: outbound alerts
CREATE TABLE IF NOT EXISTS notifications (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    channel     VARCHAR(50) NOT NULL,       -- 'sms', 'email', 'dashboard'
    recipient   VARCHAR(200) NOT NULL,
    subject     VARCHAR(500),
    body        TEXT NOT NULL,
    status      VARCHAR(20) DEFAULT 'pending', -- 'pending', 'sent', 'failed'
    error       TEXT,
    sent_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_notifications_status ON notifications(status);
CREATE INDEX idx_notifications_created ON notifications(created_at DESC);

-- ============================================================
-- SEED DATA — Default scheduled tasks
-- ============================================================

INSERT INTO scheduled_tasks (name, description, cron_expr, handler, args) VALUES
    (
        'daily_briefing',
        'Generate and deliver morning executive briefing',
        '0 8 * * *',
        'hermes.core.jobs.daily_briefing',
        '{"timezone": "America/New_York"}'
    ),
    (
        'health_check',
        'Check all infrastructure services',
        '*/15 * * * *',
        'hermes.core.jobs.infrastructure_health_check',
        '{}'
    ),
    (
        'weekly_report',
        'Generate weekly performance summary',
        '0 9 * * 1',
        'hermes.core.jobs.weekly_report',
        '{"timezone": "America/New_York"}'
    ),
    (
        'memory_consolidation',
        'Consolidate and prune old memories',
        '0 2 * * *',
        'hermes.core.jobs.consolidate_memories',
        '{"max_age_days": 90}'
    )
ON CONFLICT (name) DO NOTHING;

-- ============================================================
-- UPDATED_AT trigger function
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER memories_updated_at
    BEFORE UPDATE ON memories
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER scheduled_tasks_updated_at
    BEFORE UPDATE ON scheduled_tasks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
