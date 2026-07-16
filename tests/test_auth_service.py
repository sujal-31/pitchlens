"""Unit tests for the auth service.

Tests cover:
- Password hashing and verification
- JWT access token generation and verification
- Refresh token generation and hashing
- Token expiry values
- Error responses not revealing email existence
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.auth import (
    ACCESS_TOKEN_TTL_MINUTES,
    AuthError,
    _create_access_token,
    _create_refresh_token_value,
    _hash_password,
    _hash_refresh_token,
    _verify_password,
    verify_access_token,
)


class TestPasswordHashing:
    """Tests for bcrypt password hashing."""

    def test_hash_password_returns_bcrypt_hash(self):
        hashed = _hash_password("mypassword")
        assert hashed.startswith("$2b$")

    def test_verify_password_correct(self):
        password = "securepass123"
        hashed = _hash_password(password)
        assert _verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        hashed = _hash_password("correctpassword")
        assert _verify_password("wrongpassword", hashed) is False

    def test_hash_password_different_salts(self):
        password = "samepassword"
        hash1 = _hash_password(password)
        hash2 = _hash_password(password)
        # Different salts produce different hashes
        assert hash1 != hash2
        # But both verify correctly
        assert _verify_password(password, hash1) is True
        assert _verify_password(password, hash2) is True

    def test_password_exactly_8_chars(self):
        password = "12345678"
        hashed = _hash_password(password)
        assert _verify_password(password, hashed) is True

    def test_password_with_unicode(self):
        password = "pässwörd🔐"
        hashed = _hash_password(password)
        assert _verify_password(password, hashed) is True

    def test_password_with_special_chars(self):
        password = "p@$$w0rd!#%^&*()"
        hashed = _hash_password(password)
        assert _verify_password(password, hashed) is True


class TestJWTTokens:
    """Tests for JWT access token creation and verification."""

    def test_create_access_token_valid(self):
        user_id = str(uuid.uuid4())
        email = "test@example.com"
        token = _create_access_token(user_id, email)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_verify_access_token_valid(self):
        user_id = str(uuid.uuid4())
        email = "test@example.com"
        token = _create_access_token(user_id, email)
        payload = verify_access_token(token)
        assert payload["sub"] == user_id
        assert payload["email"] == email
        assert payload["type"] == "access"

    def test_verify_access_token_expiry_in_payload(self):
        user_id = str(uuid.uuid4())
        email = "user@test.com"
        token = _create_access_token(user_id, email)
        payload = verify_access_token(token)
        # exp should be ~15 minutes from now
        exp_time = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = exp_time - now
        # Allow a small margin for test execution time
        assert timedelta(minutes=14) < diff <= timedelta(minutes=15)

    def test_verify_access_token_invalid_string(self):
        with pytest.raises(AuthError) as exc_info:
            verify_access_token("not.a.valid.token")
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid credentials"

    def test_verify_access_token_tampered(self):
        token = _create_access_token(str(uuid.uuid4()), "test@test.com")
        # Tamper with the token
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(AuthError):
            verify_access_token(tampered)

    @patch("app.services.auth.JWT_SECRET", "test-secret")
    def test_verify_token_wrong_secret(self):
        from jose import jwt as jose_jwt

        # Create token with different secret
        payload = {
            "sub": str(uuid.uuid4()),
            "email": "test@test.com",
            "type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
        }
        token = jose_jwt.encode(payload, "wrong-secret", algorithm="HS256")
        with pytest.raises(AuthError):
            verify_access_token(token)


class TestRefreshTokens:
    """Tests for refresh token generation and hashing."""

    def test_create_refresh_token_value_unique(self):
        token1 = _create_refresh_token_value()
        token2 = _create_refresh_token_value()
        assert token1 != token2

    def test_create_refresh_token_value_length(self):
        token = _create_refresh_token_value()
        # Two uuid4 hex values = 32 + 32 = 64 chars
        assert len(token) == 64

    def test_hash_refresh_token_deterministic(self):
        token = "some-refresh-token-value"
        hash1 = _hash_refresh_token(token)
        hash2 = _hash_refresh_token(token)
        assert hash1 == hash2

    def test_hash_refresh_token_different_inputs(self):
        hash1 = _hash_refresh_token("token1")
        hash2 = _hash_refresh_token("token2")
        assert hash1 != hash2


class TestAuthError:
    """Tests for AuthError exception."""

    def test_default_message(self):
        error = AuthError()
        assert error.detail == "Invalid credentials"
        assert error.status_code == 401

    def test_custom_message(self):
        error = AuthError(detail="Custom error", status_code=400)
        assert error.detail == "Custom error"
        assert error.status_code == 400

    def test_error_does_not_reveal_email(self):
        """Auth errors should never contain email-related specifics."""
        error = AuthError()
        assert "email" not in error.detail.lower()
        assert "not found" not in error.detail.lower()
        assert "already" not in error.detail.lower()

    def test_error_does_not_reveal_password(self):
        """Auth errors should never contain password-related specifics."""
        error = AuthError()
        assert "password" not in error.detail.lower()
        assert "incorrect" not in error.detail.lower()
        assert "wrong" not in error.detail.lower()
