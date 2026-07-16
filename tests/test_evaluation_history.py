"""Unit tests for evaluation history endpoints (GET /api/evaluations)."""

import logging
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

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


def create_mock_deck(deck_id=None, user_id=None, file_name="My Pitch Deck.pdf"):
    """Create a mock Deck object."""
    deck = MagicMock()
    deck.id = deck_id or uuid.uuid4()
    deck.user_id = user_id or uuid.uuid4()
    deck.file_name = file_name
    return deck


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

    def scalar(self):
        return self._value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        if isinstance(self._value, list):
            return self._value
        return [self._value] if self._value else []


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


class TestListEvaluationsEmpty:
    """Tests for empty evaluation history."""

    @pytest.mark.asyncio
    async def test_empty_history_returns_empty_list_with_zero_total(
        self, authenticated_client, mock_db
    ):
        """When no evaluations exist, returns empty list with total=0.

        Validates: Requirement 12.5
        """
        # First call: count query returns 0
        # Second call: paginated results returns empty
        mock_db.execute = AsyncMock(
            side_effect=[
                MockScalarResult(0),  # count
                MockScalarResult([]),  # scorecards list
            ]
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/evaluations/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["page"] == 1
        assert data["page_size"] == 20


class TestListEvaluationsPagination:
    """Tests for evaluation list pagination."""

    @pytest.mark.asyncio
    async def test_pagination_defaults(self, authenticated_client, mock_user, mock_db):
        """Default pagination uses page=1 and page_size=20.

        Validates: Requirement 12.2
        """
        deck = create_mock_deck(user_id=mock_user.id)
        scorecard = create_mock_scorecard(
            user_id=mock_user.id, deck_id=deck.id, overall_score=8
        )

        mock_db.execute = AsyncMock(
            side_effect=[
                MockScalarResult(1),  # count
                MockScalarResult([scorecard]),  # results
                MockScalarResult(deck),  # deck lookup
            ]
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/evaluations/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 20
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["overall_score"] == 8
        assert data["items"][0]["deck_name"] == deck.file_name

    @pytest.mark.asyncio
    async def test_custom_page_and_page_size(
        self, authenticated_client, mock_user, mock_db
    ):
        """Custom page and page_size query params are respected.

        Validates: Requirement 12.2
        """
        deck = create_mock_deck(user_id=mock_user.id)
        scorecard = create_mock_scorecard(user_id=mock_user.id, deck_id=deck.id)

        mock_db.execute = AsyncMock(
            side_effect=[
                MockScalarResult(5),  # total count
                MockScalarResult([scorecard]),  # results for page 2
                MockScalarResult(deck),  # deck lookup
            ]
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/evaluations/?page=2&page_size=2")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["page"] == 2
        assert data["page_size"] == 2
        assert data["total"] == 5


class TestListEvaluationsSorting:
    """Tests for evaluation list sorting."""

    @pytest.mark.asyncio
    async def test_sorted_by_creation_date_descending(
        self, authenticated_client, mock_user, mock_db
    ):
        """Evaluations are returned sorted by created_at descending (newest first).

        Validates: Requirement 12.2
        """
        deck = create_mock_deck(user_id=mock_user.id)
        now = datetime.now(timezone.utc)

        # Create scorecards with different timestamps (already sorted desc)
        sc_newer = create_mock_scorecard(
            user_id=mock_user.id,
            deck_id=deck.id,
            overall_score=9,
            created_at=now,
        )
        sc_older = create_mock_scorecard(
            user_id=mock_user.id,
            deck_id=deck.id,
            overall_score=6,
            created_at=now - timedelta(days=1),
        )

        mock_db.execute = AsyncMock(
            side_effect=[
                MockScalarResult(2),  # count
                MockScalarResult([sc_newer, sc_older]),  # results (sorted by DB)
                MockScalarResult(deck),  # deck lookup for sc_newer
                MockScalarResult(deck),  # deck lookup for sc_older
            ]
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/evaluations/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["items"]) == 2
        # Newer comes first
        assert data["items"][0]["overall_score"] == 9
        assert data["items"][1]["overall_score"] == 6


class TestListEvaluationsDeckFilter:
    """Tests for deck_id filter on evaluation list."""

    @pytest.mark.asyncio
    async def test_deck_id_filter_returns_only_matching(
        self, authenticated_client, mock_user, mock_db
    ):
        """When deck_id filter is provided, only evaluations for that deck are returned.

        Validates: Requirement 12.6
        """
        deck = create_mock_deck(user_id=mock_user.id)
        scorecard = create_mock_scorecard(
            user_id=mock_user.id, deck_id=deck.id, overall_score=7
        )

        mock_db.execute = AsyncMock(
            side_effect=[
                MockScalarResult(1),  # count (filtered)
                MockScalarResult([scorecard]),  # results (filtered)
                MockScalarResult(deck),  # deck lookup
            ]
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/api/evaluations/?deck_id={deck.id}")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1


class TestGetEvaluationDetail:
    """Tests for getting a single evaluation (full scorecard)."""

    @pytest.mark.asyncio
    async def test_get_own_evaluation_returns_full_scorecard(
        self, authenticated_client, mock_user, mock_db
    ):
        """Accessing own evaluation returns the full scorecard details.

        Validates: Requirement 12.3
        """
        scorecard = create_mock_scorecard(user_id=mock_user.id, overall_score=8)

        mock_db.execute = AsyncMock(return_value=MockScalarResult(scorecard))

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/api/evaluations/{scorecard.id}")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["overall_score"] == 8
        assert "category_scores" in data
        assert "verdict_summary" in data
        assert "category_ranking" in data

    @pytest.mark.asyncio
    async def test_cross_user_access_returns_403(
        self, authenticated_client, mock_user, mock_db
    ):
        """Accessing another user's evaluation returns 403 without existence hint.

        Validates: Requirement 12.4
        """
        other_user_id = uuid.uuid4()
        scorecard = create_mock_scorecard(user_id=other_user_id)

        mock_db.execute = AsyncMock(return_value=MockScalarResult(scorecard))

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/api/evaluations/{scorecard.id}")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        data = response.json()
        assert data["detail"] == "forbidden"

    @pytest.mark.asyncio
    async def test_nonexistent_evaluation_returns_403(
        self, authenticated_client, mock_db
    ):
        """Accessing a non-existent evaluation returns 403 (same as cross-user).

        Validates: Requirement 12.4
        """
        mock_db.execute = AsyncMock(return_value=MockScalarResult(None))

        fake_id = uuid.uuid4()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/api/evaluations/{fake_id}")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        data = response.json()
        assert data["detail"] == "forbidden"


class TestUnauthorizedAccessLogging:
    """Tests for security logging on unauthorized access attempts."""

    @pytest.mark.asyncio
    async def test_cross_user_access_is_logged(
        self, authenticated_client, mock_user, mock_db, caplog
    ):
        """Unauthorized access attempts are logged with user ID and eval ID.

        Validates: Requirement 12.4
        """
        other_user_id = uuid.uuid4()
        scorecard = create_mock_scorecard(user_id=other_user_id)
        eval_id = scorecard.id

        mock_db.execute = AsyncMock(return_value=MockScalarResult(scorecard))

        with caplog.at_level(logging.WARNING, logger="app.api.evaluations"):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(f"/api/evaluations/{eval_id}")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        # Verify log message contains relevant info
        assert any("Unauthorized access attempt" in record.message for record in caplog.records)
        assert any(str(mock_user.id) in record.message for record in caplog.records)
        assert any(str(eval_id) in record.message for record in caplog.records)
