"""Scorecard serialization, validation, and database persistence service.

Provides round-trip serialization of Scorecard Pydantic models to/from JSON,
schema validation with descriptive error messages, and async DB operations.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Scorecard as DBScorecard
from app.models.schemas import CategoryScore, Scorecard


class ScorecardValidationError(Exception):
    """Raised when scorecard JSON fails schema validation.

    Attributes:
        field: The field that caused the validation failure (if identifiable).
        message: A human-readable description of the problem.
    """

    def __init__(self, message: str, field: str | None = None) -> None:
        self.field = field
        self.message = message
        super().__init__(message)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def serialize_scorecard(scorecard: Scorecard) -> dict[str, Any]:
    """Serialize a Pydantic Scorecard to a JSON-compatible dictionary.

    Handles UUID → str and datetime → ISO 8601 string conversions so the
    resulting dict is safe for JSON encoding and JSONB storage.
    """
    data = scorecard.model_dump()

    # Convert UUID fields to strings
    for key in ("id", "analysis_id", "deck_id"):
        if isinstance(data.get(key), UUID):
            data[key] = str(data[key])

    # Convert datetime to ISO string
    if isinstance(data.get("created_at"), datetime):
        data["created_at"] = data["created_at"].isoformat()

    return data


# ---------------------------------------------------------------------------
# Deserialization
# ---------------------------------------------------------------------------


def deserialize_scorecard(data: dict[str, Any]) -> Scorecard:
    """Deserialize a JSON dict back into a Pydantic Scorecard.

    Raises:
        ScorecardValidationError: If the data is malformed or missing required
            fields. The error message identifies which field is problematic.
    """
    try:
        return Scorecard.model_validate(data)
    except ValidationError as exc:
        errors = exc.errors()
        if errors:
            first = errors[0]
            field_path = " -> ".join(str(loc) for loc in first.get("loc", []))
            msg = first.get("msg", "validation error")
            raise ScorecardValidationError(
                message=f"Invalid field '{field_path}': {msg}",
                field=field_path,
            ) from exc
        raise ScorecardValidationError(
            message="Scorecard validation failed with unknown error"
        ) from exc
    except (TypeError, ValueError) as exc:
        raise ScorecardValidationError(
            message=f"Malformed scorecard data: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_scorecard_json(data: dict[str, Any]) -> Scorecard:
    """Validate a JSON dict against the Scorecard schema.

    Returns the validated Scorecard on success. Raises ScorecardValidationError
    with a descriptive message identifying the invalid/absent field on failure.
    """
    if not isinstance(data, dict):
        raise ScorecardValidationError(
            message="Scorecard data must be a JSON object (dict)",
            field=None,
        )

    # Check for required top-level fields before Pydantic validation
    required_fields = [
        "id",
        "analysis_id",
        "deck_id",
        "overall_score",
        "category_scores",
        "verdict_summary",
        "category_ranking",
        "created_at",
    ]
    missing = [f for f in required_fields if f not in data]
    if missing:
        raise ScorecardValidationError(
            message=f"Missing required field(s): {', '.join(missing)}",
            field=missing[0],
        )

    # Delegate to Pydantic for full schema validation
    return deserialize_scorecard(data)


# ---------------------------------------------------------------------------
# Database persistence
# ---------------------------------------------------------------------------


def _extract_category_columns(
    category_scores: list[CategoryScore],
) -> dict[str, Any]:
    """Extract individual category columns from the category_scores list."""
    columns: dict[str, Any] = {}
    category_map = {
        "market": "market",
        "team": "team",
        "business_model": "business_model",
        "competition": "competition",
    }

    for cs in category_scores:
        prefix = category_map.get(cs.category)
        if prefix:
            columns[f"{prefix}_score"] = cs.score
            columns[f"{prefix}_reasoning"] = cs.reasoning
            columns[f"{prefix}_suggestions"] = cs.suggestions

    return columns


async def persist_scorecard(
    session: AsyncSession,
    scorecard: Scorecard,
    user_id: UUID,
) -> DBScorecard:
    """Validate, serialize, and persist a Scorecard to the database.

    Args:
        session: Async SQLAlchemy session.
        scorecard: Validated Pydantic Scorecard instance.
        user_id: The owning user's UUID.

    Returns:
        The persisted SQLAlchemy Scorecard model instance.

    Raises:
        ScorecardValidationError: If the scorecard fails validation.
    """
    # Validate before persisting
    serialized = serialize_scorecard(scorecard)
    validate_scorecard_json(serialized)

    # Build individual category columns
    category_columns = _extract_category_columns(scorecard.category_scores)

    db_scorecard = DBScorecard(
        id=scorecard.id,
        analysis_id=scorecard.analysis_id,
        deck_id=scorecard.deck_id,
        user_id=user_id,
        overall_score=scorecard.overall_score,
        verdict_summary=scorecard.verdict_summary,
        category_ranking=scorecard.category_ranking,
        failed_categories=scorecard.failed_categories or [],
        scorecard_json=serialized,
        created_at=scorecard.created_at,
        **category_columns,
    )

    session.add(db_scorecard)
    await session.flush()
    return db_scorecard


async def get_scorecard_by_analysis(
    session: AsyncSession,
    analysis_id: UUID,
) -> Scorecard | None:
    """Retrieve a scorecard by analysis_id and deserialize from scorecard_json.

    Returns None if no scorecard exists for the given analysis_id.

    Raises:
        ScorecardValidationError: If the stored JSON is corrupted/invalid.
    """
    stmt = select(DBScorecard).where(DBScorecard.analysis_id == analysis_id)
    result = await session.execute(stmt)
    db_scorecard = result.scalar_one_or_none()

    if db_scorecard is None:
        return None

    return deserialize_scorecard(db_scorecard.scorecard_json)
