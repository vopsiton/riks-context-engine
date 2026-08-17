-- Creates the semantic_entries table used by PostgresSemanticMemory
-- (src/riks_context_engine/memory/postgres.py).

CREATE TABLE IF NOT EXISTS semantic_entries (
    id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL,
    last_accessed TIMESTAMPTZ NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 0,
    embedding JSONB
);

CREATE INDEX IF NOT EXISTS idx_semantic_subject ON semantic_entries(subject);
CREATE INDEX IF NOT EXISTS idx_semantic_predicate ON semantic_entries(predicate);
