"""Sliding window rate limiter middleware for PitchLens.

Enforces request rate limits using in-memory sliding window counters:
- Analysis endpoints (POST /api/decks): 10 requests/user/hour
- General endpoints: 60 requests/user/minute
- Auth endpoints (POST /api/auth/*): 20 requests/IP/5-minutes

Returns 429 Too Many Requests with Retry-After header on limit breach.
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from jose import JWTError, jwt

from app.api.dependencies import JWT_ALGORITHM, JWT_SECRET


@dataclass
class RateLimitConfig:
    """Configuration for a rate limit rule."""

    max_requests: int
    window_seconds: int


# Rate limit configurations per endpoint category
ANALYSIS_LIMIT = RateLimitConfig(max_requests=10, window_seconds=3600)  # 10/hour
GENERAL_LIMIT = RateLimitConfig(max_requests=60, window_seconds=60)  # 60/minute
AUTH_LIMIT = RateLimitConfig(max_requests=20, window_seconds=300)  # 20/5-minutes


@dataclass
class SlidingWindowCounter:
    """In-memory sliding window counter for rate limiting.

    Stores timestamps of requests and removes expired entries on each check.
    """

    timestamps: list[float] = field(default_factory=list)

    def count_in_window(self, now: float, window_seconds: int) -> int:
        """Count requests within the sliding window, pruning expired entries."""
        cutoff = now - window_seconds
        self.timestamps = [ts for ts in self.timestamps if ts > cutoff]
        return len(self.timestamps)

    def add(self, now: float) -> None:
        """Record a new request timestamp."""
        self.timestamps.append(now)

    def earliest_expiry(self, now: float, window_seconds: int) -> float:
        """Get seconds until the oldest request in the window expires."""
        if not self.timestamps:
            return 0.0
        cutoff = now - window_seconds
        valid = [ts for ts in self.timestamps if ts > cutoff]
        if not valid:
            return 0.0
        oldest = min(valid)
        return (oldest + window_seconds) - now


class RateLimiterStore:
    """Thread-safe in-memory store for rate limit counters.

    Maintains separate counters per tracking key (user_id or IP address)
    and per endpoint category.
    """

    def __init__(self) -> None:
        # Key: (tracking_key, category) -> SlidingWindowCounter
        self._counters: dict[tuple[str, str], SlidingWindowCounter] = defaultdict(
            SlidingWindowCounter
        )

    def check_and_record(
        self, key: str, category: str, config: RateLimitConfig, now: float | None = None
    ) -> tuple[bool, float]:
        """Check if request is allowed and record it if so.

        Args:
            key: Tracking key (user_id or IP address).
            category: Endpoint category ("analysis", "general", "auth").
            config: Rate limit configuration for this category.
            now: Current timestamp (defaults to time.time()).

        Returns:
            Tuple of (allowed: bool, retry_after_seconds: float).
            If allowed is True, retry_after is 0.
            If allowed is False, retry_after indicates seconds to wait.
        """
        if now is None:
            now = time.time()

        counter = self._counters[(key, category)]
        current_count = counter.count_in_window(now, config.window_seconds)

        if current_count >= config.max_requests:
            retry_after = counter.earliest_expiry(now, config.window_seconds)
            return False, retry_after

        counter.add(now)
        return True, 0.0

    def get_counter(self, key: str, category: str) -> SlidingWindowCounter:
        """Get the counter for a given key and category (for testing)."""
        return self._counters[(key, category)]


# Global store instance
_store = RateLimiterStore()


def get_rate_limiter_store() -> RateLimiterStore:
    """Get the global rate limiter store instance."""
    return _store


def reset_rate_limiter_store() -> None:
    """Reset the global rate limiter store (for testing)."""
    global _store
    _store = RateLimiterStore()


def classify_endpoint(method: str, path: str) -> str:
    """Classify a request into an endpoint category.

    Categories:
    - "analysis": POST /api/decks (deck upload triggers analysis)
    - "auth": POST /api/auth/* (registration, login, refresh)
    - "general": all other endpoints

    Args:
        method: HTTP method (GET, POST, etc.)
        path: Request path.

    Returns:
        Category string: "analysis", "auth", or "general".
    """
    # Normalize path
    normalized = path.rstrip("/").lower()

    # Auth endpoints: /api/auth/*
    if normalized.startswith("/api/auth"):
        return "auth"

    # Analysis endpoint: POST /api/decks
    if method.upper() == "POST" and normalized == "/api/decks":
        return "analysis"

    return "general"


def get_rate_limit_config(category: str) -> RateLimitConfig:
    """Get the rate limit configuration for an endpoint category."""
    if category == "analysis":
        return ANALYSIS_LIMIT
    elif category == "auth":
        return AUTH_LIMIT
    else:
        return GENERAL_LIMIT


def extract_client_ip(request: Request) -> str:
    """Extract the client IP address from the request.

    Checks X-Forwarded-For header first (for proxied requests),
    then falls back to the direct client host.
    """
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        # Take the first IP in the chain (original client)
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def extract_user_id_from_token(request: Request) -> str | None:
    """Attempt to extract user_id from the Authorization Bearer token.

    Returns None if no valid token is present (unauthenticated request).
    Does not raise exceptions - this is a best-effort extraction for
    rate limiting purposes.
    """
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:]  # Strip "Bearer " prefix

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        return user_id if user_id else None
    except JWTError:
        return None


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that enforces sliding window rate limits.

    Classifies each request by endpoint category, determines the
    tracking key (user_id for authenticated, IP for unauthenticated),
    and checks against the appropriate rate limit.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process a request through rate limiting."""
        store = get_rate_limiter_store()

        # Classify the endpoint
        category = classify_endpoint(request.method, request.url.path)

        # Determine tracking key
        if category == "auth":
            # Auth endpoints are tracked by IP (unauthenticated)
            tracking_key = extract_client_ip(request)
        else:
            # Authenticated endpoints tracked by user_id
            user_id = extract_user_id_from_token(request)
            if user_id:
                tracking_key = user_id
            else:
                # If no valid token, skip rate limiting for non-auth endpoints
                # (the auth middleware will reject the request anyway)
                return await call_next(request)

        # Get rate limit config for this category
        config = get_rate_limit_config(category)

        # Check rate limit
        allowed, retry_after = store.check_and_record(
            key=tracking_key, category=category, config=config
        )

        if not allowed:
            retry_after_int = max(1, int(retry_after) + 1)  # Round up, minimum 1 second
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too Many Requests",
                    "retry_after": retry_after_int,
                },
                headers={"Retry-After": str(retry_after_int)},
            )

        return await call_next(request)
