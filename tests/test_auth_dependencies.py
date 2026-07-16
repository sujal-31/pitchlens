"""Unit tests for app/api/dependencies.py - JWT middleware and refresh token validation."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt

from app.api.dependencies import (
    JWT_ALGORITHM,
    JWT_SECRET,
    RefreshTokenRequest,
    get_current_user,
    validate_refresh_token,
)


def create_access_token(user_id: str, expires_delta: timedelta | None = None) -> str:
    """Helper to create a JWT access token for testing."""
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=15))
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_expired_token(user_id: str) -> str:
    """Helper to create an expired JWT token."""
    return create_access_token(user_id, expires_delta=timedelta(minutes=-5))


@pytest.fixture
def mock_db():
    """Create a mock async database session."""
    db = AsyncMock()
    return db


@pytest.fixture
def valid_user():
    """Create a mock User object."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "test@example.com"
    return user


class TestGetCurrentUser:
    """Tests for the get_current_user dependency."""

    @pytest.mark.asyncio
    async def test_valid_token_returns_user(self, mock_db, valid_user):
        """Valid JWT with existing user returns the user object."""
        token = create_access_token(str(valid_user.id))
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials=token
        )

        # Mock DB query to return the user
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = valid_user
        mock_db.execute.return_value = mock_result

        result = await get_current_user(credentials=credentials, db=mock_db)
        assert result == valid_user

    @pytest.mark.asyncio
    async def test_missing_credentials_raises_401(self, mock_db):
        """No Authorization header raises 401."""
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=None, db=mock_db)

        assert exc_info.value.status_code == 401
        assert "Could not validate credentials" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_expired_token_raises_401(self, mock_db):
        """Expired JWT raises 401 with 'Token has expired' message."""
        token = create_expired_token(str(uuid.uuid4()))
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials=token
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=credentials, db=mock_db)

        assert exc_info.value.status_code == 401
        assert "Token has expired" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_invalid_token_raises_401(self, mock_db):
        """Malformed JWT raises 401."""
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="not.a.valid.jwt"
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=credentials, db=mock_db)

        assert exc_info.value.status_code == 401
        assert "Could not validate credentials" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_token_with_wrong_secret_raises_401(self, mock_db):
        """JWT signed with wrong secret raises 401."""
        payload = {
            "sub": str(uuid.uuid4()),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
        }
        token = jwt.encode(payload, "wrong-secret", algorithm=JWT_ALGORITHM)
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials=token
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=credentials, db=mock_db)

        assert exc_info.value.status_code == 401
        assert "Could not validate credentials" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_token_without_sub_claim_raises_401(self, mock_db):
        """JWT without 'sub' claim raises 401."""
        payload = {"exp": datetime.now(timezone.utc) + timedelta(minutes=15)}
        token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials=token
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=credentials, db=mock_db)

        assert exc_info.value.status_code == 401
        assert "Could not validate credentials" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_user_not_found_raises_401(self, mock_db):
        """Valid JWT but user not in DB raises 401."""
        user_id = str(uuid.uuid4())
        token = create_access_token(user_id)
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials=token
        )

        # Mock DB query to return None (user not found)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=credentials, db=mock_db)

        assert exc_info.value.status_code == 401
        assert "Could not validate credentials" in exc_info.value.detail


class TestValidateRefreshToken:
    """Tests for the validate_refresh_token function."""

    @pytest.mark.asyncio
    async def test_valid_refresh_token(self, mock_db):
        """Valid, non-expired, non-revoked refresh token succeeds."""
        mock_token = MagicMock()
        mock_token.revoked = False
        mock_token.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        mock_token.user_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_token
        mock_db.execute.return_value = mock_result

        result = await validate_refresh_token("valid-token-hash", mock_db)
        assert result == mock_token

    @pytest.mark.asyncio
    async def test_nonexistent_refresh_token_raises_401(self, mock_db):
        """Token hash not in DB raises 401."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await validate_refresh_token("nonexistent-hash", mock_db)

        assert exc_info.value.status_code == 401
        assert "Invalid refresh token" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_revoked_refresh_token_raises_401(self, mock_db):
        """Revoked refresh token raises 401."""
        mock_token = MagicMock()
        mock_token.revoked = True
        mock_token.expires_at = datetime.now(timezone.utc) + timedelta(days=7)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_token
        mock_db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await validate_refresh_token("revoked-token-hash", mock_db)

        assert exc_info.value.status_code == 401
        assert "revoked" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_expired_refresh_token_raises_401(self, mock_db):
        """Expired refresh token raises 401."""
        mock_token = MagicMock()
        mock_token.revoked = False
        mock_token.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_token
        mock_db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await validate_refresh_token("expired-token-hash", mock_db)

        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail


class TestRefreshTokenRequest:
    """Tests for the RefreshTokenRequest schema."""

    def test_valid_request(self):
        """Valid refresh token string is accepted."""
        req = RefreshTokenRequest(refresh_token="some-token-value")
        assert req.refresh_token == "some-token-value"

    def test_missing_refresh_token_raises(self):
        """Missing refresh_token field raises validation error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RefreshTokenRequest()
