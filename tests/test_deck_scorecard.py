"""Unit tests for GET /api/decks/{deck_id}/scorecard endpoint."""

import logging
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient

from app.main import app


def create_mock_user(user_id=None):
    """Create a mock authenticated user."""
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.email = "test@example.com"
    return user


def create_mock_scorecard(
    scorecard_id=None,
    user_id=None,
    deck_id=None,
    overall_score=7,
    created_at=None,
    scorecard_json=None,
):
    """Create a mock Scorecard object."""
    sc = MagicMock()
    sc.id = scorecard_id or uuid.uuid4()
    sc.user_id = user_id or uuid.uuid4()
    sc.deck_id = deck_id or uuid.uuid4()
    sc.overall_score = overall_score
    sc.created_at = created_at or datetime.now(timezone.utc)
    sc.scorecard_json = scorecard_json or {
        "id": str(sc.id),
        "analysis_id": str(uuid.uuid4()),
        "deck_id": str(sc.deck_id),
        "overall_score": overall_score,
        "category_scores": [
            {
                "category": "market",
                "score": 8,
                "reasoning": "Strong market opportunity with clear TAM/SAM/SOM analysis and growing market trends identified.",
                "suggestions": ["Include more competitor analysis"],
            }
        ],
        "verdict_summary": (
            "This pitch deck demonstrates a solid understanding of the market opportunity "
            "with strong fundamentals across key evaluation criteria. The team composition "
            "and business model show promise for future growth."
        ),
        "category_ranking": ["market", "team", "business_model", "competition"],
        "failed_categories": [],
        "created_at": sc.created_at.isoformat(),
    }
    return sc


class MockScalarResult:
    """Mock for SQLAlchemy scalar result."""

    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


@pytest.fixture
def mock_user():
    return create_mock_user()


@pytest.fixture
def mock_db():
    """Create a mock async database session."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


@pytest.fixture
def authenticated_client(mock_user, mock_db):
    """Override dependencies to simulate an authenticated user with a mock DB."""
    from app.api.dependencies import get_current_user
    from app.db.database import get_db

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    yield
    app.dependency_overrides.clear()


class TestGetDeckScorecard:
    """Tests for GET /api/decks/{deck_id}/scorecard."""

    @pytest.mark.asyncio
    async def test_returns_scorecard_for_own_deck(
        self, authenticated_client, mock_user, mock_db
    ):
        """Accessing own deck scorecard returns the full scorecard.

        Validates: Requirement 9.4
        """
        deck_id = uuid.uuid4()
        scorecard = create_mock_scorecard(
            user_id=mock_user.id, deck_id=deck_id, overall_score=8
        )

        mock_db.execute = AsyncMock(return_value=MockScalarResult(scorecard))

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/api/decks/{deck_id}/scorecard")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["overall_score"] == 8
        assert "category_scores" in data
        assert "verdict_summary" in data
        assert "category_ranking" in data

    @pytest.mark.asyncio
    async def test_returns_404_when_no_scorecard_exists(
        self, authenticated_client, mock_db
    ):
        """When no scorecard exists for the deck, returns 404.

        Validates: Requirement 9.4
        """
        deck_id = uuid.uuid4()
        mock_db.execute = AsyncMock(return_value=MockScalarResult(None))

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/api/decks/{deck_id}/scorecard")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        data = response.json()
        assert data["detail"] == "Scorecard not found."

    @pytest.mark.asyncio
    async def test_returns_403_for_other_users_scorecard(
        self, authenticated_client, mock_user, mock_db
    ):
        """Accessing another user's scorecard returns 403 without revealing existence.

        Validates: Requirement 12.4
        """
        deck_id = uuid.uuid4()
        other_user_id = uuid.uuid4()
        scorecard = create_mock_scorecard(
            user_id=other_user_id, deck_id=deck_id, overall_score=9
        )

        mock_db.execute = AsyncMock(return_value=MockScalarResult(scorecard))

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/api/decks/{deck_id}/scorecard")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        data = response.json()
        assert data["detail"] == "forbidden"

    @pytest.mark.asyncio
    async def test_cross_user_access_is_logged(
        self, authenticated_client, mock_user, mock_db, caplog
    ):
        """Unauthorized access attempts are logged with user and deck IDs.

        Validates: Requirement 12.4
        """
        deck_id = uuid.uuid4()
        other_user_id = uuid.uuid4()
        scorecard = create_mock_scorecard(
            user_id=other_user_id, deck_id=deck_id
        )

        mock_db.execute = AsyncMock(return_value=MockScalarResult(scorecard))

        with caplog.at_level(logging.WARNING, logger="app.api.decks"):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(f"/api/decks/{deck_id}/scorecard")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert any("Unauthorized access attempt" in record.message for record in caplog.records)
        assert any(str(mock_user.id) in record.message for record in caplog.records)
        assert any(str(deck_id) in record.message for record in caplog.records)
