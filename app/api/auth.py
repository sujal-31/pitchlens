"""Authentication API routes for PitchLens.

Provides endpoints for user registration, login, and token refresh.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.api.dependencies import RefreshTokenRequest
from app.models.schemas import LoginRequest, RegisterRequest, TokenResponse
from app.services.auth import AuthError, login, refresh_token, register

router = APIRouter()


@router.post("/register", response_model=TokenResponse)
async def register_user(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Register a new user account.

    Returns an access token on successful registration.
    """
    try:
        return await register(email=body.email, password=body.password, db=db)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.post("/login", response_model=TokenResponse)
async def login_user(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Authenticate and receive access + refresh tokens."""
    try:
        return await login(email=body.email, password=body.password, db=db)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Exchange a valid refresh token for a new access token."""
    try:
        return await refresh_token(token=body.refresh_token, db=db)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
