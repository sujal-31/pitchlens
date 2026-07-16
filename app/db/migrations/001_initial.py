"""Initial database migration for PitchLens.

Creates all tables, indexes, and enables the pgvector extension.
This script can be run directly against a PostgreSQL database or
used as a reference for Alembic migrations.

Tables created:
- users
- refresh_tokens
- decks
- analyses
- scorecards
- chat_sessions
- chat_messages
- deck_embeddings (with pgvector)
- rate_limit_events
"""

import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/pitchlens"
)

# Full SQL migration script
MIGRATION_SQL = """
-- Enable pgvector extension for vector similarity search
CREATE EXTENSION IF NOT EXISTS vector;

-- Enable uuid generation
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Users
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Refresh tokens
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash VARCHAR(255) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Decks
CREATE TABLE IF NOT EXISTS decks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    file_name VARCHAR(255) NOT NULL,
    file_path VARCHAR(1024) NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    page_count INTEGER NOT NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Analyses (pipeline runs)
CREATE TABLE IF NOT EXISTS analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    deck_id UUID NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error_message TEXT
);

-- Scorecards
CREATE TABLE IF NOT EXISTS scorecards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_id UUID NOT NULL UNIQUE REFERENCES analyses(id) ON DELETE CASCADE,
    deck_id UUID NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    overall_score INTEGER NOT NULL CHECK (overall_score BETWEEN 1 AND 10),
    market_score INTEGER CHECK (market_score BETWEEN 1 AND 10),
    market_reasoning TEXT,
    market_suggestions JSONB,
    team_score INTEGER CHECK (team_score BETWEEN 1 AND 10),
    team_reasoning TEXT,
    team_suggestions JSONB,
    business_model_score INTEGER CHECK (business_model_score BETWEEN 1 AND 10),
    business_model_reasoning TEXT,
    business_model_suggestions JSONB,
    competition_score INTEGER CHECK (competition_score BETWEEN 1 AND 10),
    competition_reasoning TEXT,
    competition_suggestions JSONB,
    verdict_summary TEXT NOT NULL,
    category_ranking JSONB NOT NULL,
    failed_categories JSONB,
    scorecard_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Chat sessions
CREATE TABLE IF NOT EXISTS chat_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    deck_id UUID NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Chat messages
CREATE TABLE IF NOT EXISTS chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    cited_sections JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Vector embeddings for RAG (pgvector)
CREATE TABLE IF NOT EXISTS deck_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    deck_id UUID NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    chunk_text TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    section_category VARCHAR(50),
    embedding vector(1536) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_deck_embeddings_deck_id
    ON deck_embeddings(deck_id);

CREATE INDEX IF NOT EXISTS idx_deck_embeddings_vector
    ON deck_embeddings USING ivfflat (embedding vector_cosine_ops);

-- Rate limiting
CREATE TABLE IF NOT EXISTS rate_limit_events (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    ip_address INET,
    endpoint_category VARCHAR(50) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rate_limit_user
    ON rate_limit_events(user_id, endpoint_category, occurred_at);

CREATE INDEX IF NOT EXISTS idx_rate_limit_ip
    ON rate_limit_events(ip_address, endpoint_category, occurred_at);
"""

# Rollback SQL for undoing this migration
ROLLBACK_SQL = """
DROP TABLE IF EXISTS rate_limit_events CASCADE;
DROP TABLE IF EXISTS deck_embeddings CASCADE;
DROP TABLE IF EXISTS chat_messages CASCADE;
DROP TABLE IF EXISTS chat_sessions CASCADE;
DROP TABLE IF EXISTS scorecards CASCADE;
DROP TABLE IF EXISTS analyses CASCADE;
DROP TABLE IF EXISTS decks CASCADE;
DROP TABLE IF EXISTS refresh_tokens CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP EXTENSION IF EXISTS vector;
"""


async def upgrade() -> None:
    """Apply the migration - create all tables and indexes."""
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as conn:
        # Execute statements one at a time for better error handling
        statements = [
            stmt.strip()
            for stmt in MIGRATION_SQL.split(";")
            if stmt.strip() and not stmt.strip().startswith("--")
        ]
        for statement in statements:
            await conn.execute(text(statement))
    await engine.dispose()
    print("Migration 001_initial: upgrade complete")


async def downgrade() -> None:
    """Rollback the migration - drop all tables."""
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as conn:
        statements = [
            stmt.strip()
            for stmt in ROLLBACK_SQL.split(";")
            if stmt.strip() and not stmt.strip().startswith("--")
        ]
        for statement in statements:
            await conn.execute(text(statement))
    await engine.dispose()
    print("Migration 001_initial: downgrade complete")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "downgrade":
        asyncio.run(downgrade())
    else:
        asyncio.run(upgrade())
