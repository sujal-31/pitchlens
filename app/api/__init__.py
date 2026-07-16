"""API routes package.

Aggregates all endpoint routers for mounting in the main application.
"""

from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.decks import router as decks_router
from app.api.evaluations import router as evaluations_router

router = APIRouter()

# Auth routes
router.include_router(auth_router, prefix="/auth", tags=["auth"])

# Deck routes
router.include_router(decks_router, prefix="/decks", tags=["decks"])

# Evaluation history routes
router.include_router(evaluations_router, prefix="/evaluations", tags=["evaluations"])
