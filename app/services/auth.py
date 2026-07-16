"""Authentication service for PitchLens.

Handles user registration, login, and token refresh with:
- Password hashing via bcrypt
- JWT signing with HS256
- Access token TTL: 15 minutes
- Refresh token TTL: 7 days
- Error responses that do not reveal email existence or which credential failed
"""

import hashlib
import os
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RefreshToken, User
from app.models.schemas import TokenResponse

# Configuration
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TTL_MINUTES = 15
REFRESH_TOKEN_TTL_DAYS = 7


class AuthError(Exception):
    """Authentication error that provides a generic message to the client."""

    def __init__(self, detail: str = "Invalid credentials", status_code: int = 401):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


def _hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its bcrypt hash."""
    password_bytes = password.encode("utf-8")
    hash_bytes = password_hash.encode("utf-8")
    return bcrypt.checkpw(password_bytes, hash_bytes)


def _create_access_token(user_id: str, email: str) -> str:
    """Create a JWT access token with 15-minute expiry."""
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=ACCESS_TOKEN_TTL_MINUTES)
    payload = {
        "sub": user_id,
        "email": email,
        "type": "access",
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _create_refresh_token_value() -> str:
    """Generate a cryptographically random refresh token value."""
    return uuid.uuid4().hex + uuid.uuid4().hex


def _hash_refresh_token(token: str) -> str:
    """Hash a refresh token for secure storage using SHA-256."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def register(
    email: str, password: str, db: AsyncSession
) -> TokenResponse:
    """Register a new user and return an access token.

    Args:
        email: Valid email address.
        password: Password with at least 8 characters.
        db: Async database session.

    Returns:
        TokenResponse with access token (15 min TTL).

    Raises:
        AuthError: If registration fails (generic message, does not reveal
                   whether email already exists).
    """
    if len(password) < 8:
        raise AuthError(
            detail="Invalid credentials", status_code=400
        )

    password_hash = _hash_password(password)

    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=password_hash,
    )

    try:
        db.add(user)
        await db.flush()
    except IntegrityError:
        await db.rollback()
        # Do not reveal that the email is already registered
        raise AuthError(
            detail="Invalid credentials", status_code=400
        )

    access_token = _create_access_token(
        user_id=str(user.id), email=user.email
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=None,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_TTL_MINUTES * 60,
    )


async def login(
    email: str, password: str, db: AsyncSession
) -> TokenResponse:
    """Authenticate a user and return access + refresh tokens.

    Args:
        email: User's email address.
        password: User's password.
        db: Async database session.

    Returns:
        TokenResponse with access token (15 min) and refresh token (7 days).

    Raises:
        AuthError: If credentials are invalid (generic message, does not
                   reveal whether email exists or password was wrong).
    """
    # Look up user by email
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        # Do not reveal that the email does not exist
        raise AuthError(detail="Invalid credentials", status_code=401)

    if not _verify_password(password, user.password_hash):
        # Do not reveal that the password was incorrect
        raise AuthError(detail="Invalid credentials", status_code=401)

    # Generate access token
    access_token = _create_access_token(
        user_id=str(user.id), email=user.email
    )

    # Generate refresh token and store its hash in the database
    raw_refresh_token = _create_refresh_token_value()
    token_hash = _hash_refresh_token(raw_refresh_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_TTL_DAYS)

    refresh_token_record = RefreshToken(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
        revoked=False,
    )
    db.add(refresh_token_record)
    await db.flush()

    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_TTL_MINUTES * 60,
    )


async def refresh_token(
    token: str, db: AsyncSession
) -> TokenResponse:
    """Issue a new access token using a valid refresh token.

    Args:
        token: The raw refresh token value.
        db: Async database session.

    Returns:
        TokenResponse with a new access token (15 min TTL).

    Raises:
        AuthError: If the refresh token is invalid, expired, or revoked.
    """
    token_hash = _hash_refresh_token(token)

    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    refresh_record = result.scalar_one_or_none()

    if refresh_record is None:
        raise AuthError(detail="Invalid credentials", status_code=401)

    if refresh_record.revoked:
        raise AuthError(detail="Invalid credentials", status_code=401)

    if refresh_record.expires_at.replace(tzinfo=timezone.utc) < datetime.now(
        timezone.utc
    ):
        raise AuthError(detail="Invalid credentials", status_code=401)

    # Fetch the user to include email in the token
    user_result = await db.execute(
        select(User).where(User.id == refresh_record.user_id)
    )
    user = user_result.scalar_one_or_none()

    if user is None:
        raise AuthError(detail="Invalid credentials", status_code=401)

    # Issue new access token
    access_token = _create_access_token(
        user_id=str(user.id), email=user.email
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=None,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_TTL_MINUTES * 60,
    )


def verify_access_token(token: str) -> dict:
    """Verify and decode a JWT access token.

    Args:
        token: The JWT access token string.

    Returns:
        The decoded token payload.

    Raises:
        AuthError: If the token is invalid or expired.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise AuthError(detail="Invalid credentials", status_code=401)
        return payload
    except JWTError:
        raise AuthError(detail="Invalid credentials", status_code=401)
