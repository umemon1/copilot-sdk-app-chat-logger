-- Copilot Chat Logger - Database Schema
-- Run: psql $DATABASE_URL -f schema.sql

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    developer       TEXT NOT NULL,
    model           TEXT,
    cwd             TEXT,
    source          TEXT,               -- "startup", "resume", "new"
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at        TIMESTAMPTZ,
    end_reason      TEXT,               -- "complete", "error", "abort", "timeout", "user_exit"
    final_message   TEXT
);

CREATE TABLE IF NOT EXISTS prompt_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    prompt_text     TEXT NOT NULL,
    response_text   TEXT,
    duration_ms     INTEGER
);

CREATE TABLE IF NOT EXISTS tool_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    phase           TEXT NOT NULL,       -- "pre" or "post"
    tool_name       TEXT NOT NULL,
    tool_args       JSONB,
    tool_result     JSONB,
    permission      TEXT                -- "allow", "deny", "ask"
);

CREATE TABLE IF NOT EXISTS error_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    error_message   TEXT NOT NULL,
    error_context   TEXT,               -- "model_call", "tool_execution", "system", "user_input"
    recoverable     BOOLEAN DEFAULT FALSE
);

-- Indexes for dashboard queries
CREATE INDEX IF NOT EXISTS idx_sessions_developer ON sessions(developer);
CREATE INDEX IF NOT EXISTS idx_sessions_started_at ON sessions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_prompt_logs_session ON prompt_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_tool_logs_session ON tool_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_error_logs_session ON error_logs(session_id);
