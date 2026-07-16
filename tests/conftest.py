"""Shared test fixtures for PitchLens tests."""

import os

# Set test environment variables before importing app modules
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-testing")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/pitchlens_test"
)
