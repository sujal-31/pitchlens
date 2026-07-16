"""Unit tests for the evaluation history endpoints (GET /api/evaluations)."""

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


def create_mock_deck(deck_id=None, user_id=None, file_name="my_deck.pdf"):
    """Create a mock Deck object."""
    deck = MagicMock()
    deck.id = deck_id or uuid.uuid4()
    deck.user_id = user_id or uuid.uuid4()
    deck.file_name = file_name
    return deck


def create_mock_scorecard(
    user_id,
    deck_id=None,
    overall_score=7,
    created_at=None,
    scorecard_id=None,
):
    """Create a mock Scorecard ORM object."""
    sc = MagicMock()
    sc.id = scorecard_id or uuid.uuid4()
    sc.user_id = user_id
    sc.deck_id = deck_id or uuid.uuid4()
    sc.overall_score = overall_score
    sc.created_at = created_at or datetime.now(timezone.utc)
    sc.scorecard_json = {
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


class TestListEvaluations:
    """Tests for GET /api/evaluations."""

    @pytest.mark.asyncio
    async def test_empty_list_returns_zero_total(self, authenticated_client, mock_db):
        """When no evaluations exist, returns empty list with zero total."""
        # Mock count query returning 0
        mock_db.execute = AsyncMock(
            side_effect=[
                MockScalarResult(0),  # count
                MockScalarResult([]),  # scorecards list (not reached due to early return)
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

    @pytest.mark.asyncio
    async def test_pagination_defaults(self, authenticated_client, mock_db, mock_user):
        """Default pagination is page=1, page_size=20."""
        deck_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        deck = create_mock_deck(deck_id=deck_id, user_id=mock_user.id, file_name="my_deck.pdf")
        scorecard = create_mock_scorecard(mock_user.id, deck_id=deck_id, created_at=now)

        mock_db.execute = AsyncMock(
            side_effect=[
                MockScalarResult(1),  # count
                MockScalarResult([scorecard]),  # scorecards
                MockScalarResult(deck),  # deck lookup
            ]
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/evaluations/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 1
        assert data["page"] == 1
        assert data["page_size"] == 20
        assert len(data["items"]) == 1
        assert data["items"][0]["deck_name"] == "my_deck.pdf"
        assert data["items"][0]["overall_score"] == 7

    @pytest.mark.asyncio
    async def test_custom_pagination_params(self, authenticated_client, mock_db, mock_user):
        """Custom page and page_size are respected."""
        mock_db.execute = AsyncMock(
            side_effect=[
                MockScalarResult(50),  # count
                MockScalarResult([]),  # empty page (page 3 with page_size 10 but mocked empty)
            ]
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/evaluations/?page=3&page_size=10")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["page"] == 3
        assert data["page_size"] == 10
        assert data["total"] == 50

    @pytest.mark.asyncio
    async def test_results_sorted_by_created_at_descending(
        self, authenticated_client, mock_db, mock_user
    ):
        """Results are returned sorted by created_at descending."""
        deck_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        older = now - timedelta(days=1)
        deck = create_mock_deck(deck_id=deck_id, user_id=mock_user.id, file_name="deck.pdf")

        sc1 = create_mock_scorecard(mock_user.id, deck_id=deck_id, created_at=now, overall_score=8)
        sc2 = create_mock_scorecard(mock_user.id, deck_id=deck_id, created_at=older, overall_score=5)

        mock_db.execute = AsyncMock(
            side_effect=[
                MockScalarResult(2),  # count
                MockScalarResult([sc1, sc2]),  # scorecards (sorted by DB)
                MockScalarResult(deck),  # deck lookup for sc1
                MockScalarResult(deck),  # deck lookup for sc2
            ]
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/evaluations/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["items"]) == 2
        assert data["items"][0]["overall_score"] == 8
        assert data["items"][1]["overall_score"] == 5

    @pytest.mark.asyncio
    async def test_deck_id_filter(self, authenticated_client, mock_db, mock_user):
        """When deck_id is provided, only matching evaluations are returned."""
        target_deck_id = uuid.uuid4()
        deck = create_mock_deck(deck_id=target_deck_id, user_id=mock_user.id, file_name="filtered_deck.pdf")
        sc = create_mock_scorecard(mock_user.id, deck_id=target_deck_id, overall_score=9)

        mock_db.execute = AsyncMock(
            side_effect=[
                MockScalarResult(1),  # count (filtered)
                MockScalarResult([sc]),  # scorecards (filtered)
                MockScalarResult(deck),  # deck lookup
            ]
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/api/evaluations/?deck_id={target_deck_id}")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["overall_score"] == 9


class TestGetEvaluation:
    """Tests for GET /api/evaluations/{eval_id}."""

    @pytest.mark.asyncio
    async def test_get_own_evaluation(self, authenticated_client, mock_db, mock_user):
        """User can retrieve their own evaluation's full scorecard."""
        eval_id = uuid.uuid4()
        sc = create_mock_scorecard(mock_user.id, scorecard_id=eval_id)

        mock_db.execute = AsyncMock(return_value=MockScalarResult(sc))

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/api/evaluations/{eval_id}")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["overall_score"] == 7
        assert "verdict_summary" in data
        assert "category_scores" in data
        assert "category_ranking" in data

    @pytest.mark.asyncio
    async def test_cross_user_access_returns_403(self, authenticated_client, mock_db, mock_user):
        """Accessing another user's evaluation returns 403 without existence hint."""
        other_user_id = uuid.uuid4()
        eval_id = uuid.uuid4()
        sc = create_mock_scorecard(other_user_id, scorecard_id=eval_id)

        mock_db.execute = AsyncMock(return_value=MockScalarResult(sc))

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/api/evaluations/{eval_id}")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"] == "forbidden"

    @pytest.mark.asyncio
    async def test_nonexistent_evaluation_returns_403(self, authenticated_client, mock_db):
        """Requesting a non-existent evaluation returns 403 (not 404)."""
        eval_id = uuid.uuid4()

        mock_db.execute = AsyncMock(return_value=MockScalarResult(None))

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/api/evaluations/{eval_id}")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"] == "forbidden"

    @pytest.mark.asyncio
    async def test_cross_user_access_is_logged(self, authenticated_client, mock_db, mock_user):
        """Unauthorized access attempts are logged with user_id and eval_id."""
        other_user_id = uuid.uuid4()
        eval_id = uuid.uuid4()
        sc = create_mock_scorecard(other_user_id, scorecard_id=eval_id)

        mock_db.execute = AsyncMock(return_value=MockScalarResult(sc))

        with patch("app.api.evaluations.logger") as mock_logger:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(f"/api/evaluations/{eval_id}")

            assert response.status_code == status.HTTP_403_FORBIDDEN
            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            assert str(mock_user.id) in str(call_args)
            assert str(eval_id) in str(call_args)


class TestEvaluationsAuthentication:
    """Tests for authentication requirements."""

    @pytest.mark.asyncio
    async def test_unauthenticated_list_returns_401(self):
        """Unauthenticated request to list evaluations returns 401."""
        app.dependency_overrides.clear()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/evaluations/")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_unauthenticated_get_returns_401(self):
        """Unauthenticated request to get evaluation returns 401."""
        app.dependency_overrides.clear()
        eval_id = uuid.uuid4()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/api/evaluations/{eval_id}")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
