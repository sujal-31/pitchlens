"""API routes for pitch deck upload and management."""

import asyncio
import io
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from PyPDF2 import PdfReader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.db.database import get_db
from app.db.models import Analysis, Deck, Scorecard, User
from app.models.schemas import (
    ChatRequest,
    ChatResponse,
    DeckUploadResponse,
    Scorecard as ScorecardSchema,
)
from app.services.injection_guard import scan
from app.services.orchestrator import run_pipeline
from app.services.rag_engine import rag_engine

logger = logging.getLogger(__name__)

router = APIRouter()

# Constants
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_PAGE_COUNT = 50
UPLOAD_DIR = Path("uploads")


@router.post("", response_model=DeckUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_deck(
    file: UploadFile,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DeckUploadResponse:
    """Upload a pitch deck PDF for analysis.

    Validates the file is a valid PDF within size and page limits,
    stores it in persistent storage, creates database records, and
    triggers the analysis pipeline as a background task.

    Returns 202 Accepted immediately. The frontend should connect
    to the WebSocket at /ws/analysis/{analysis_id} to track progress.
    """
    # Read file content into memory for validation
    content = await file.read()
    file_size = len(content)

    # Validate file size
    if file_size > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File size limit exceeded. Maximum allowed size is 20 MB.",
        )

    # Validate PDF format and page count
    try:
        pdf_reader = PdfReader(io.BytesIO(content))
        page_count = len(pdf_reader.pages)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file format. Only valid PDF files are accepted.",
        )

    if page_count == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file format. The PDF contains zero extractable pages.",
        )

    if page_count > MAX_PAGE_COUNT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Page limit exceeded. Maximum allowed is 50 pages.",
        )

    # Store file in persistent storage
    file_id = uuid.uuid4()
    file_extension = ".pdf"
    stored_filename = f"{file_id}{file_extension}"
    file_path = UPLOAD_DIR / stored_filename

    try:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(content)
    except OSError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Storage failure. Unable to save the uploaded file.",
        )

    # Create database records
    try:
        deck = Deck(
            id=file_id,
            user_id=current_user.id,
            file_name=file.filename or "untitled.pdf",
            file_path=str(file_path),
            file_size_bytes=file_size,
            page_count=page_count,
        )
        db.add(deck)
        await db.flush()

        analysis = Analysis(
            id=uuid.uuid4(),
            deck_id=deck.id,
            user_id=current_user.id,
            status="pending",
        )
        db.add(analysis)
        await db.flush()
    except Exception:
        # Clean up stored file if DB operation fails
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Storage failure. Unable to save the uploaded file.",
        )

    # Trigger the analysis pipeline as a background task.
    # The response is returned immediately (202 Accepted) without waiting
    # for the pipeline to complete. The frontend connects via WebSocket
    # to /ws/analysis/{analysis_id} to receive real-time progress updates.
    asyncio.create_task(
        run_pipeline(
            deck_id=deck.id,
            analysis_id=analysis.id,
            user_id=current_user.id,
            pdf_bytes=content,
        )
    )

    return DeckUploadResponse(
        deck_id=deck.id,
        analysis_id=analysis.id,
        file_name=deck.file_name,
        page_count=deck.page_count,
    )


@router.post("/{deck_id}/chat", response_model=ChatResponse)
async def chat_with_deck(
    deck_id: uuid.UUID,
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """Send a follow-up question about an analyzed pitch deck.

    Validates deck ownership, scans for prompt injection, then routes
    through the RAG engine to provide grounded answers.

    Requirements: 11.1, 11.2
    """
    # Verify deck exists and belongs to the current user
    result = await db.execute(
        select(Deck).where(Deck.id == deck_id, Deck.user_id == current_user.id)
    )
    deck = result.scalar_one_or_none()
    if deck is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deck not found.",
        )

    # Run injection guard scan on the message
    scan_result = scan(body.message, str(current_user.id))
    if not scan_result.allowed:
        if scan_result.error and "service unavailable" in scan_result.error.lower():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Service temporarily unavailable. Please try again later.",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Security violation: request blocked.",
        )

    # Route through RAG engine
    response = await rag_engine.query(deck_id, current_user.id, body.message, db)
    return response


@router.get("/{deck_id}/scorecard", response_model=ScorecardSchema)
async def get_deck_scorecard(
    deck_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScorecardSchema:
    """Get the scorecard for a specific deck or analysis.

    Accepts either a deck_id or analysis_id in the path parameter.
    Returns 404 if no scorecard exists.
    Returns 403 Forbidden for cross-user access without revealing
    whether the scorecard exists.

    Requirements: 9.4, 12.4
    """
    from sqlalchemy import or_

    # Look up the scorecard by deck_id OR analysis_id (frontend passes analysis_id)
    result = await db.execute(
        select(Scorecard).where(
            or_(Scorecard.deck_id == deck_id, Scorecard.analysis_id == deck_id)
        )
    )
    scorecard = result.scalar_one_or_none()

    # If not found OR belongs to another user, enforce ownership
    if scorecard is None or scorecard.user_id != current_user.id:
        if scorecard is not None and scorecard.user_id != current_user.id:
            # Log the unauthorized access attempt
            logger.warning(
                "Unauthorized access attempt: user=%s tried to access scorecard for deck=%s at=%s",
                current_user.id,
                deck_id,
                datetime.now(timezone.utc).isoformat(),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="forbidden",
            )
        # No scorecard exists for this deck
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scorecard not found.",
        )

    # Return the full scorecard from the stored JSON
    return ScorecardSchema(**scorecard.scorecard_json)
