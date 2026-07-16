"""API routes for evaluation history retrieval.

Provides endpoints to list past evaluations with pagination and
retrieve full scorecard details for a specific evaluation.

Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.db.database import get_db
from app.db.models import Deck, Scorecard, User
from app.models.schemas import (
    EvaluationListItem,
    PaginatedEvaluations,
    Scorecard as ScorecardSchema,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=PaginatedEvaluations)
async def list_evaluations(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    deck_id: Optional[uuid.UUID] = Query(default=None, description="Filter by deck ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedEvaluations:
    """List past evaluations for the authenticated user.

    Returns a paginated list sorted by creation date descending.
    Optionally filters by deck_id.

    Requirements: 12.1, 12.2, 12.5, 12.6
    """
    # Base filter: only current user's scorecards
    filters = [Scorecard.user_id == current_user.id]

    # Apply optional deck_id filter
    if deck_id is not None:
        filters.append(Scorecard.deck_id == deck_id)

    # Get total count
    count_query = select(func.count()).select_from(Scorecard).where(*filters)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # If no results, return early with empty list
    if total == 0:
        return PaginatedEvaluations(
            items=[],
            total=0,
            page=page,
            page_size=page_size,
        )

    # Fetch paginated results sorted by created_at descending
    offset = (page - 1) * page_size
    items_query = (
        select(Scorecard)
        .where(*filters)
        .order_by(Scorecard.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(items_query)
    scorecards = result.scalars().all()

    # Build response items with deck names
    items = []
    for sc in scorecards:
        deck_result = await db.execute(select(Deck).where(Deck.id == sc.deck_id))
        deck = deck_result.scalar_one_or_none()
        deck_name = deck.file_name if deck else "Unknown"

        items.append(
            EvaluationListItem(
                id=sc.id,
                deck_name=deck_name,
                overall_score=sc.overall_score,
                created_at=sc.created_at,
            )
        )

    return PaginatedEvaluations(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{eval_id}", response_model=ScorecardSchema)
async def get_evaluation(
    eval_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScorecardSchema:
    """Get full scorecard details for a specific evaluation.

    Returns 403 Forbidden for cross-user access without revealing
    whether the evaluation exists. Logs unauthorized access attempts.

    Requirements: 12.3, 12.4
    """
    # Look up the scorecard without filtering by user
    result = await db.execute(select(Scorecard).where(Scorecard.id == eval_id))
    scorecard = result.scalar_one_or_none()

    # If not found OR belongs to another user, return 403
    # This prevents information leakage about resource existence
    if scorecard is None or scorecard.user_id != current_user.id:
        if scorecard is not None and scorecard.user_id != current_user.id:
            # Log the unauthorized access attempt
            logger.warning(
                "Unauthorized access attempt: user=%s tried to access evaluation=%s at=%s",
                current_user.id,
                eval_id,
                datetime.now(timezone.utc).isoformat(),
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="forbidden",
        )

    # Return the full scorecard from the stored JSON
    return ScorecardSchema(**scorecard.scorecard_json)
