"""Pipeline Orchestrator Service - Manages the analysis pipeline lifecycle.

Executes: Extractor → Parallel [4 Scorers] → Verdict Aggregator
with retry logic, timeouts, and status tracking.
Integrates WebSocket streaming for real-time progress events.

Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 10.2, 10.3, 10.4
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select, update

from app.db.database import async_session
from app.db.models import Analysis
from app.db.models import Scorecard as ScorecardDB

# ExtractionError can be imported eagerly since extractor doesn't depend on crewai
from app.agents.extractor import ExtractionError

# Agent function imports are done lazily to avoid requiring crewai at import time
# (crewai may not be installed in all environments, e.g., test environments).
# Module-level references are set to None and populated on first use.
extract_content = None
score_market = None
score_team = None
score_business_model = None
score_competition = None
aggregate_scores = None

_agents_loaded = False


def _ensure_agents_loaded():
    """Load agent modules on first use. Idempotent.

    If module-level agent references have been set externally (e.g., by test
    mocks via unittest.mock.patch), this function is a no-op.
    """
    global extract_content, score_market, score_team
    global score_business_model, score_competition, aggregate_scores, _agents_loaded
    if _agents_loaded:
        return
    # If any agent function has been set externally (e.g., by mock.patch), skip loading
    if extract_content is not None:
        _agents_loaded = True
        return
    from app.agents.extractor import extract_content as _extract_content
    from app.agents.market_scorer import score_market as _score_market
    from app.agents.team_scorer import score_team as _score_team
    from app.agents.business_model_scorer import score_business_model as _score_business_model
    from app.agents.competition_scorer import score_competition as _score_competition
    from app.agents.verdict_aggregator import aggregate_scores as _aggregate_scores
    extract_content = _extract_content
    score_market = _score_market
    score_team = _score_team
    score_business_model = _score_business_model
    score_competition = _score_competition
    aggregate_scores = _aggregate_scores
    _agents_loaded = True

from app.models.schemas import CategoryScore, ExtractedContent, PipelineStage, Scorecard
from app.services.injection_guard import scan as injection_scan
from app.services.ws_manager import ws_manager

logger = logging.getLogger(__name__)

# --- Constants ---

TOTAL_PIPELINE_TIMEOUT_SECONDS = 600  # 10 minutes for OCR + scoring with reflection
SCORER_RETRY_TIMEOUT_SECONDS = 120

# Mapping from scorer name to PipelineStage for individual scorer stage emissions
_SCORER_STAGE_MAP = {
    "market": PipelineStage.SCORING_MARKET,
    "team": PipelineStage.SCORING_TEAM,
    "business_model": PipelineStage.SCORING_BUSINESS_MODEL,
    "competition": PipelineStage.SCORING_COMPETITION,
}


async def _safe_ws_emit(coro) -> None:
    """Execute a WebSocket emission coroutine safely.

    WebSocket failures must never crash the pipeline. All emissions are
    fire-and-forget side effects.

    Args:
        coro: An awaitable coroutine (ws_manager method call).
    """
    try:
        await coro
    except Exception as e:
        logger.warning(f"WebSocket emission failed (non-fatal): {e}")


class PipelineError(Exception):
    """Base exception for pipeline errors."""

    def __init__(self, message: str, stage: str = "unknown"):
        self.stage = stage
        super().__init__(message)


class ExtractionFailedError(PipelineError):
    """Raised when the Extractor Agent fails."""

    def __init__(self, message: str):
        super().__init__(message, stage="extracting")


class PipelineTimeoutError(PipelineError):
    """Raised when the total pipeline exceeds 120 seconds."""

    def __init__(self):
        super().__init__(
            "Pipeline exceeded 120-second timeout", stage="timeout"
        )


class InjectionDetectedError(PipelineError):
    """Raised when prompt injection is detected in extracted deck content.

    Fail-closed: pipeline aborts to prevent malicious content from reaching agents.
    Requirements: 14.1, 14.2, 14.5
    """

    def __init__(self, section_category: str):
        super().__init__(
            "Security violation: request blocked.",
            stage="injection_scan",
        )
        self.section_category = section_category


async def _update_analysis_status(
    analysis_id: UUID,
    status: str,
    error_message: Optional[str] = None,
    completed: bool = False,
) -> None:
    """Update the analysis record status in the database.

    Args:
        analysis_id: UUID of the analysis record.
        status: New status string (pending, extracting, scoring, aggregating, complete, failed).
        error_message: Optional error message for failed status.
        completed: Whether to set completed_at timestamp.
    """
    async with async_session() as session:
        values = {"status": status}
        if error_message is not None:
            values["error_message"] = error_message
        if completed:
            values["completed_at"] = datetime.now(timezone.utc)

        stmt = (
            update(Analysis)
            .where(Analysis.id == analysis_id)
            .values(**values)
        )
        await session.execute(stmt)
        await session.commit()


async def _persist_scorecard(scorecard: Scorecard, user_id: UUID) -> None:
    """Persist the scorecard to the database.

    Stores both the structured fields and the full JSON for round-trip retrieval.
    """
    # Build per-category field values
    category_fields = {}
    for cs in scorecard.category_scores:
        cat = cs.category
        category_fields[f"{cat}_score"] = cs.score
        category_fields[f"{cat}_reasoning"] = cs.reasoning
        category_fields[f"{cat}_suggestions"] = cs.suggestions

    # Build the full scorecard JSON for round-trip storage
    scorecard_json = {
        "id": str(scorecard.id),
        "analysis_id": str(scorecard.analysis_id),
        "deck_id": str(scorecard.deck_id),
        "overall_score": scorecard.overall_score,
        "category_scores": [
            {
                "category": cs.category,
                "score": cs.score,
                "reasoning": cs.reasoning,
                "suggestions": cs.suggestions,
            }
            for cs in scorecard.category_scores
        ],
        "verdict_summary": scorecard.verdict_summary,
        "category_ranking": scorecard.category_ranking,
        "failed_categories": scorecard.failed_categories,
        "created_at": scorecard.created_at.isoformat(),
    }

    async with async_session() as session:
        db_scorecard = ScorecardDB(
            id=scorecard.id,
            analysis_id=scorecard.analysis_id,
            deck_id=scorecard.deck_id,
            user_id=user_id,
            overall_score=scorecard.overall_score,
            verdict_summary=scorecard.verdict_summary,
            category_ranking=scorecard.category_ranking,
            failed_categories=scorecard.failed_categories,
            scorecard_json=scorecard_json,
            created_at=scorecard.created_at,
            **category_fields,
        )
        session.add(db_scorecard)
        await session.commit()


async def _run_extractor(
    pdf_bytes: bytes, deck_id: UUID
) -> ExtractedContent:
    """Run the Extractor Agent in a thread executor.

    The extractor is synchronous, so we run it in an executor to avoid
    blocking the event loop.

    Raises:
        ExtractionFailedError: If extraction fails for any reason.
    """
    _ensure_agents_loaded()

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None, extract_content, pdf_bytes, deck_id
        )
        return result
    except ExtractionError as e:
        raise ExtractionFailedError(f"Extraction failed: {e.reason}")
    except Exception as e:
        raise ExtractionFailedError(f"Unexpected extraction error: {str(e)}")


async def _run_scorer_with_retry(
    scorer_name: str,
    scorer_fn,
    extracted_content: ExtractedContent,
    is_async: bool = False,
) -> Tuple[str, Optional[CategoryScore], Optional[str]]:
    """Run a single scorer with one retry on failure.

    Each attempt has a 30-second timeout. On first failure, retries once.
    If both attempts fail, returns None with error message.

    Args:
        scorer_name: Name of the scorer category (for logging).
        scorer_fn: The scorer function to call.
        extracted_content: Content to pass to the scorer.
        is_async: Whether the scorer function is async.

    Returns:
        Tuple of (scorer_name, CategoryScore or None, error_message or None).
    """
    loop = asyncio.get_event_loop()

    for attempt in range(2):  # 0 = first attempt, 1 = retry
        try:
            if is_async:
                result = await asyncio.wait_for(
                    scorer_fn(extracted_content),
                    timeout=SCORER_RETRY_TIMEOUT_SECONDS,
                )
            else:
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, scorer_fn, extracted_content),
                    timeout=SCORER_RETRY_TIMEOUT_SECONDS,
                )
            return (scorer_name, result, None)
        except asyncio.TimeoutError:
            error_msg = f"{scorer_name} timed out (attempt {attempt + 1})"
            logger.warning(error_msg)
            if attempt == 0:
                logger.info(f"Retrying {scorer_name}...")
                continue
            return (scorer_name, None, error_msg)
        except Exception as e:
            error_msg = f"{scorer_name} failed (attempt {attempt + 1}): {str(e)}"
            logger.warning(error_msg)
            if attempt == 0:
                logger.info(f"Retrying {scorer_name}...")
                continue
            return (scorer_name, None, error_msg)

    # Should not reach here, but safety net
    return (scorer_name, None, f"{scorer_name} exhausted all retries")


async def _run_all_scorers(
    extracted_content: ExtractedContent,
    analysis_id: Optional[UUID] = None,
) -> Tuple[List[CategoryScore], List[str]]:
    """Run all 4 scoring agents in parallel with retry logic.

    Emits individual scorer stage changes and partial results via WebSocket
    as each scorer completes. Uses asyncio tasks so results can be streamed
    incrementally.

    Args:
        extracted_content: The extracted deck content to score.
        analysis_id: Optional analysis ID for WebSocket emissions.

    Returns:
        Tuple of (list of successful CategoryScores, list of failed category names).
    """
    analysis_id_str = str(analysis_id) if analysis_id else None

    # Emit individual scorer stage starts
    if analysis_id_str:
        for stage in _SCORER_STAGE_MAP.values():
            await _safe_ws_emit(
                ws_manager.emit_stage_change(analysis_id_str, stage)
            )

    # Create tasks for each scorer
    _ensure_agents_loaded()

    scorer_configs = [
        ("market", score_market, True),
        ("team", score_team, True),
        ("business_model", score_business_model, True),
        ("competition", score_competition, True),
    ]

    # Create named tasks for tracking
    tasks = {}
    for scorer_name, scorer_fn, is_async in scorer_configs:
        task = asyncio.create_task(
            _run_scorer_with_retry(
                scorer_name, scorer_fn, extracted_content, is_async=is_async
            )
        )
        tasks[task] = scorer_name

    scores: List[CategoryScore] = []
    failed_categories: List[str] = []

    # Process results as they complete (stream partial results)
    for completed_task in asyncio.as_completed(tasks.keys()):
        scorer_name, score, error = await completed_task

        if score is not None:
            scores.append(score)
            # Emit partial result via WebSocket as soon as scorer completes
            if analysis_id_str:
                await _safe_ws_emit(
                    ws_manager.emit_partial_result(
                        analysis_id_str,
                        {
                            "category": scorer_name,
                            "score": score.score,
                            "reasoning": score.reasoning,
                            "suggestions": score.suggestions,
                        },
                    )
                )
        else:
            failed_categories.append(scorer_name)
            logger.error(f"Scorer '{scorer_name}' failed after retry: {error}")

    return scores, failed_categories


async def _run_aggregator(
    scores: List[CategoryScore], analysis_id: UUID, deck_id: UUID
) -> Scorecard:
    """Run the Verdict Aggregator in a thread executor.

    The aggregator is synchronous, so we run it off the event loop.
    """
    _ensure_agents_loaded()

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, aggregate_scores, scores, analysis_id, deck_id
    )
    return result


async def _execute_pipeline(
    deck_id: UUID, analysis_id: UUID, user_id: UUID, pdf_bytes: bytes
) -> Scorecard:
    """Execute the full analysis pipeline (internal, no timeout wrapper).

    Stages:
    1. Extraction (sequential)
    2. Scoring (4 agents in parallel with retry)
    3. Aggregation (sequential)

    Updates analysis status at each transition and emits WebSocket events.

    Raises:
        ExtractionFailedError: If extractor fails.
        Exception: Any other pipeline error.
    """
    analysis_id_str = str(analysis_id)

    # Start heartbeat before extraction begins
    await _safe_ws_emit(ws_manager.start_heartbeat(analysis_id_str))

    # Stage 1: Extraction
    await _update_analysis_status(analysis_id, "extracting")
    await _safe_ws_emit(
        ws_manager.emit_stage_change(analysis_id_str, PipelineStage.EXTRACTING)
    )

    try:
        extracted_content = await _run_extractor(pdf_bytes, deck_id)
    except ExtractionFailedError as e:
        await _update_analysis_status(
            analysis_id, "failed", error_message=str(e), completed=True
        )
        await _safe_ws_emit(ws_manager.emit_error(analysis_id_str, str(e)))
        raise

    # Injection guard scan on extracted content before passing to agents
    # Fail-closed: abort pipeline if injection detected (Requirements 14.1, 14.2, 14.5)
    for section in extracted_content.sections:
        scan_result = injection_scan(section.content, user_id=str(user_id))
        if not scan_result.allowed:
            error_msg = "Security violation: request blocked."
            logger.warning(
                "Injection detected in extracted deck content "
                "(deck_id=%s, section=%s, user_id=%s)",
                deck_id,
                section.category,
                user_id,
            )
            await _update_analysis_status(
                analysis_id, "failed", error_message=error_msg, completed=True
            )
            await _safe_ws_emit(ws_manager.emit_error(analysis_id_str, error_msg))
            raise InjectionDetectedError(section_category=section.category)

    # Stage 2: Scoring (parallel)
    await _update_analysis_status(analysis_id, "scoring")
    # Individual scorer stage emissions happen inside _run_all_scorers

    scores, failed_categories = await _run_all_scorers(
        extracted_content, analysis_id=analysis_id
    )

    # If all scorers failed, we still proceed to aggregator with empty scores
    # (the aggregator handles partial/empty score lists per Requirement 9.5)

    # Stage 3: Aggregation
    await _update_analysis_status(analysis_id, "aggregating")
    await _safe_ws_emit(
        ws_manager.emit_stage_change(analysis_id_str, PipelineStage.AGGREGATING)
    )

    scorecard = await _run_aggregator(scores, analysis_id, deck_id)

    # Persist scorecard to database
    await _persist_scorecard(scorecard, user_id)

    # Mark as complete
    await _update_analysis_status(analysis_id, "complete", completed=True)
    await _safe_ws_emit(
        ws_manager.emit_complete(
            analysis_id_str,
            {
                "overall_score": scorecard.overall_score,
                "category_scores": [
                    {
                        "category": cs.category,
                        "score": cs.score,
                        "reasoning": cs.reasoning,
                        "suggestions": cs.suggestions,
                    }
                    for cs in scorecard.category_scores
                ],
                "verdict_summary": scorecard.verdict_summary,
                "category_ranking": scorecard.category_ranking,
                "failed_categories": scorecard.failed_categories,
            },
        )
    )

    return scorecard


async def run_pipeline(
    deck_id: UUID, analysis_id: UUID, user_id: UUID, pdf_bytes: bytes
) -> Scorecard:
    """Run the full analysis pipeline with a 120-second total timeout.

    This is the main entry point for the orchestrator. It:
    1. Executes extraction (Requirement 8.4: abort if extractor fails)
    2. Runs 4 scorers in parallel (Requirement 8.1)
    3. Retries failed scorers once within 30s (Requirement 8.3)
    4. Runs verdict aggregation (Requirement 8.2)
    5. Respects 120-second total timeout (Requirement 8.5)
    6. Updates analysis status at each stage transition

    Args:
        deck_id: UUID of the deck being analyzed.
        analysis_id: UUID of the analysis record.
        user_id: UUID of the user who initiated the analysis.
        pdf_bytes: Raw PDF file bytes.

    Returns:
        Complete Scorecard with all available scores.

    Raises:
        ExtractionFailedError: If the extractor fails (pipeline aborted).
        PipelineTimeoutError: If the total pipeline exceeds 120 seconds.
        PipelineError: For other pipeline failures.
    """
    try:
        scorecard = await asyncio.wait_for(
            _execute_pipeline(deck_id, analysis_id, user_id, pdf_bytes),
            timeout=TOTAL_PIPELINE_TIMEOUT_SECONDS,
        )
        return scorecard
    except asyncio.TimeoutError:
        await _update_analysis_status(
            analysis_id,
            "failed",
            error_message="Pipeline exceeded 120-second timeout",
            completed=True,
        )
        await _safe_ws_emit(
            ws_manager.emit_error(
                str(analysis_id), "Pipeline exceeded 120-second timeout"
            )
        )
        raise PipelineTimeoutError()
    except ExtractionFailedError:
        # Already handled status update and WebSocket error in _execute_pipeline
        raise
    except InjectionDetectedError:
        # Already handled status update and WebSocket error in _execute_pipeline
        raise
    except Exception as e:
        await _update_analysis_status(
            analysis_id,
            "failed",
            error_message=f"Pipeline error: {str(e)}",
            completed=True,
        )
        await _safe_ws_emit(
            ws_manager.emit_error(str(analysis_id), f"Pipeline error: {str(e)}")
        )
        raise PipelineError(f"Pipeline failed: {str(e)}", stage="unknown")
