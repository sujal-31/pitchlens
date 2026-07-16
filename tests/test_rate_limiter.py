"""Unit tests for the sliding window rate limiter middleware."""

import time

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.testclient import TestClient
from fastapi import FastAPI, Request

from app.middleware.rate_limiter import (
    RateLimiterStore,
    RateLimitConfig,
    SlidingWindowCounter,
    classify_endpoint,
    extract_client_ip,
    extract_user_id_from_token,
    get_rate_limit_config,
    ANALYSIS_LIMIT,
    GENERAL_LIMIT,
    AUTH_LIMIT,
    RateLimiterMiddleware,
    reset_rate_limiter_store,
)


class TestSlidingWindowCounter:
    """Tests for the SlidingWindowCounter class."""

    def test_empty_counter_returns_zero(self):
        counter = SlidingWindowCounter()
        assert counter.count_in_window(time.time(), 60) == 0

    def test_add_increments_count(self):
        counter = SlidingWindowCounter()
        now = time.time()
        counter.add(now)
        counter.add(now + 1)
        assert counter.count_in_window(now + 1, 60) == 2

    def test_expired_entries_are_pruned(self):
        counter = SlidingWindowCounter()
        now = 1000.0
        # Add entries in the past (outside 60-second window)
        counter.add(now - 100)
        counter.add(now - 70)
        # Add entries within window
        counter.add(now - 30)
        counter.add(now - 10)

        assert counter.count_in_window(now, 60) == 2

    def test_earliest_expiry_returns_correct_wait(self):
        counter = SlidingWindowCounter()
        now = 1000.0
        # Oldest entry was at now - 50 with 60-second window
        # It expires at (now-50) + 60 = now + 10
        counter.add(now - 50)
        counter.add(now - 30)

        expiry = counter.earliest_expiry(now, 60)
        assert abs(expiry - 10.0) < 0.01

    def test_earliest_expiry_empty(self):
        counter = SlidingWindowCounter()
        assert counter.earliest_expiry(time.time(), 60) == 0.0


class TestRateLimiterStore:
    """Tests for the RateLimiterStore."""

    def test_allows_requests_under_limit(self):
        store = RateLimiterStore()
        config = RateLimitConfig(max_requests=5, window_seconds=60)
        now = 1000.0

        for i in range(5):
            allowed, retry_after = store.check_and_record("user1", "general", config, now + i)
            assert allowed is True
            assert retry_after == 0.0

    def test_blocks_request_at_limit(self):
        store = RateLimiterStore()
        config = RateLimitConfig(max_requests=3, window_seconds=60)
        now = 1000.0

        # Fill up the limit
        for i in range(3):
            allowed, _ = store.check_and_record("user1", "general", config, now + i)
            assert allowed is True

        # Next request should be blocked
        allowed, retry_after = store.check_and_record("user1", "general", config, now + 3)
        assert allowed is False
        assert retry_after > 0

    def test_different_keys_are_independent(self):
        store = RateLimiterStore()
        config = RateLimitConfig(max_requests=2, window_seconds=60)
        now = 1000.0

        # User1 uses their limit
        store.check_and_record("user1", "general", config, now)
        store.check_and_record("user1", "general", config, now + 1)
        allowed, _ = store.check_and_record("user1", "general", config, now + 2)
        assert allowed is False

        # User2 should still be allowed
        allowed, _ = store.check_and_record("user2", "general", config, now + 2)
        assert allowed is True

    def test_different_categories_are_independent(self):
        store = RateLimiterStore()
        config = RateLimitConfig(max_requests=2, window_seconds=60)
        now = 1000.0

        # Fill analysis limit
        store.check_and_record("user1", "analysis", config, now)
        store.check_and_record("user1", "analysis", config, now + 1)
        allowed, _ = store.check_and_record("user1", "analysis", config, now + 2)
        assert allowed is False

        # General should still be allowed for same user
        allowed, _ = store.check_and_record("user1", "general", config, now + 2)
        assert allowed is True

    def test_allows_after_window_expires(self):
        store = RateLimiterStore()
        config = RateLimitConfig(max_requests=2, window_seconds=60)
        now = 1000.0

        # Fill the limit
        store.check_and_record("user1", "general", config, now)
        store.check_and_record("user1", "general", config, now + 1)
        allowed, _ = store.check_and_record("user1", "general", config, now + 2)
        assert allowed is False

        # After window expires, should be allowed again
        allowed, _ = store.check_and_record("user1", "general", config, now + 61)
        assert allowed is True


class TestClassifyEndpoint:
    """Tests for endpoint classification logic."""

    def test_post_api_decks_is_analysis(self):
        assert classify_endpoint("POST", "/api/decks") == "analysis"

    def test_post_api_decks_trailing_slash(self):
        assert classify_endpoint("POST", "/api/decks/") == "analysis"

    def test_get_api_decks_is_general(self):
        assert classify_endpoint("GET", "/api/decks") == "general"

    def test_auth_register_is_auth(self):
        assert classify_endpoint("POST", "/api/auth/register") == "auth"

    def test_auth_login_is_auth(self):
        assert classify_endpoint("POST", "/api/auth/login") == "auth"

    def test_auth_refresh_is_auth(self):
        assert classify_endpoint("POST", "/api/auth/refresh") == "auth"

    def test_general_endpoints(self):
        assert classify_endpoint("GET", "/api/evaluations") == "general"
        assert classify_endpoint("GET", "/api/decks/123/scorecard") == "general"
        assert classify_endpoint("POST", "/api/decks/123/chat") == "general"

    def test_health_is_general(self):
        assert classify_endpoint("GET", "/health") == "general"


class TestGetRateLimitConfig:
    """Tests for rate limit config retrieval."""

    def test_analysis_config(self):
        config = get_rate_limit_config("analysis")
        assert config.max_requests == 10
        assert config.window_seconds == 3600

    def test_auth_config(self):
        config = get_rate_limit_config("auth")
        assert config.max_requests == 20
        assert config.window_seconds == 300

    def test_general_config(self):
        config = get_rate_limit_config("general")
        assert config.max_requests == 60
        assert config.window_seconds == 60


class TestExtractClientIp:
    """Tests for client IP extraction."""

    def test_extracts_from_forwarded_for(self):
        request = MagicMock(spec=Request)
        request.headers = {"x-forwarded-for": "192.168.1.1, 10.0.0.1"}
        request.client = MagicMock()
        request.client.host = "127.0.0.1"

        assert extract_client_ip(request) == "192.168.1.1"

    def test_falls_back_to_client_host(self):
        request = MagicMock(spec=Request)
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "10.0.0.5"

        assert extract_client_ip(request) == "10.0.0.5"

    def test_no_client_returns_unknown(self):
        request = MagicMock(spec=Request)
        request.headers = {}
        request.client = None

        assert extract_client_ip(request) == "unknown"


class TestExtractUserIdFromToken:
    """Tests for JWT user ID extraction."""

    def test_no_auth_header_returns_none(self):
        request = MagicMock(spec=Request)
        request.headers = {}
        assert extract_user_id_from_token(request) is None

    def test_non_bearer_returns_none(self):
        request = MagicMock(spec=Request)
        request.headers = {"authorization": "Basic abc123"}
        assert extract_user_id_from_token(request) is None

    def test_invalid_token_returns_none(self):
        request = MagicMock(spec=Request)
        request.headers = {"authorization": "Bearer invalid.token.here"}
        assert extract_user_id_from_token(request) is None

    def test_valid_token_returns_user_id(self):
        from jose import jwt as jose_jwt
        from app.api.dependencies import JWT_SECRET, JWT_ALGORITHM

        token = jose_jwt.encode({"sub": "user-123"}, JWT_SECRET, algorithm=JWT_ALGORITHM)
        request = MagicMock(spec=Request)
        request.headers = {"authorization": f"Bearer {token}"}

        assert extract_user_id_from_token(request) == "user-123"

    def test_token_without_sub_returns_none(self):
        from jose import jwt as jose_jwt
        from app.api.dependencies import JWT_SECRET, JWT_ALGORITHM

        token = jose_jwt.encode({"some": "data"}, JWT_SECRET, algorithm=JWT_ALGORITHM)
        request = MagicMock(spec=Request)
        request.headers = {"authorization": f"Bearer {token}"}

        assert extract_user_id_from_token(request) is None


class TestRateLimiterMiddlewareIntegration:
    """Integration tests for the rate limiter middleware with FastAPI."""

    def setup_method(self):
        """Reset the rate limiter store before each test."""
        reset_rate_limiter_store()

    def _create_app(self) -> FastAPI:
        """Create a minimal FastAPI app with rate limiter middleware."""
        app = FastAPI()
        app.add_middleware(RateLimiterMiddleware)

        @app.post("/api/auth/login")
        async def login():
            return {"status": "ok"}

        @app.post("/api/auth/register")
        async def register():
            return {"status": "ok"}

        @app.post("/api/decks")
        async def upload_deck():
            return {"status": "ok"}

        @app.get("/api/evaluations")
        async def evaluations():
            return {"status": "ok"}

        return app

    def test_auth_endpoint_rate_limited_by_ip(self):
        """Auth endpoints should be rate limited by IP with 20/5-min."""
        app = self._create_app()
        client = TestClient(app)

        # Make 20 requests (should all succeed)
        for _ in range(20):
            resp = client.post("/api/auth/login")
            assert resp.status_code == 200

        # 21st request should be rate limited
        resp = client.post("/api/auth/login")
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        assert int(resp.headers["Retry-After"]) > 0

    def test_analysis_endpoint_rate_limited_by_user(self):
        """Analysis endpoints should be rate limited per user at 10/hour."""
        from jose import jwt as jose_jwt
        from app.api.dependencies import JWT_SECRET, JWT_ALGORITHM

        app = self._create_app()
        client = TestClient(app)

        token = jose_jwt.encode({"sub": "user-abc"}, JWT_SECRET, algorithm=JWT_ALGORITHM)
        headers = {"Authorization": f"Bearer {token}"}

        # Make 10 requests (should all succeed)
        for _ in range(10):
            resp = client.post("/api/decks", headers=headers)
            assert resp.status_code == 200

        # 11th request should be rate limited
        resp = client.post("/api/decks", headers=headers)
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers

    def test_general_endpoint_rate_limited_by_user(self):
        """General endpoints should be rate limited per user at 60/min."""
        from jose import jwt as jose_jwt
        from app.api.dependencies import JWT_SECRET, JWT_ALGORITHM

        app = self._create_app()
        client = TestClient(app)

        token = jose_jwt.encode({"sub": "user-xyz"}, JWT_SECRET, algorithm=JWT_ALGORITHM)
        headers = {"Authorization": f"Bearer {token}"}

        # Make 60 requests (should all succeed)
        for _ in range(60):
            resp = client.get("/api/evaluations", headers=headers)
            assert resp.status_code == 200

        # 61st request should be rate limited
        resp = client.get("/api/evaluations", headers=headers)
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers

    def test_unauthenticated_non_auth_endpoint_passes_through(self):
        """Requests without auth tokens on non-auth endpoints skip rate limiting."""
        app = self._create_app()
        client = TestClient(app)

        # No auth header on general endpoint - should pass through
        # (the auth middleware downstream will reject it, but rate limiter won't)
        resp = client.get("/api/evaluations")
        assert resp.status_code == 200

    def test_429_response_has_retry_after_header(self):
        """Rate limited response must include Retry-After header with seconds."""
        app = self._create_app()
        client = TestClient(app)

        # Exhaust auth limit
        for _ in range(20):
            client.post("/api/auth/login")

        resp = client.post("/api/auth/login")
        assert resp.status_code == 429
        retry_after = int(resp.headers["Retry-After"])
        assert retry_after >= 1

    def test_429_response_body(self):
        """Rate limited response body should contain detail and retry_after."""
        app = self._create_app()
        client = TestClient(app)

        # Exhaust auth limit
        for _ in range(20):
            client.post("/api/auth/login")

        resp = client.post("/api/auth/login")
        body = resp.json()
        assert body["detail"] == "Too Many Requests"
        assert "retry_after" in body
        assert body["retry_after"] >= 1

    def test_different_users_independent_limits(self):
        """Different users should have independent rate limits."""
        from jose import jwt as jose_jwt
        from app.api.dependencies import JWT_SECRET, JWT_ALGORITHM

        app = self._create_app()
        client = TestClient(app)

        token_a = jose_jwt.encode({"sub": "user-a"}, JWT_SECRET, algorithm=JWT_ALGORITHM)
        token_b = jose_jwt.encode({"sub": "user-b"}, JWT_SECRET, algorithm=JWT_ALGORITHM)

        # User A uses up analysis limit
        for _ in range(10):
            client.post("/api/decks", headers={"Authorization": f"Bearer {token_a}"})

        # User A blocked
        resp = client.post("/api/decks", headers={"Authorization": f"Bearer {token_a}"})
        assert resp.status_code == 429

        # User B should still be allowed
        resp = client.post("/api/decks", headers={"Authorization": f"Bearer {token_b}"})
        assert resp.status_code == 200
