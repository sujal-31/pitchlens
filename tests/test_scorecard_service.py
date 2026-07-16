"""Unit tests for scorecard serialization, validation, and persistence service.

Tests cover:
- Serialize Scorecard objects to JSON (Req 16.1)
- Deserialize stored JSON back into Scorecard objects without data loss (Req 16.2)
- Round-trip serialization: serialize → deserialize produces equal object (Req 16.3)
- Malformed/missing required fields returns descriptive parsing error (Req 16.4)
- Validate Scorecard JSON against schema before persisting (Req 16.5)
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from app.models.schemas import CategoryScore, Scorecard
from app.services.scorecard_service import (
    ScorecardValidationError,
    deserialize_scorecard,
    serialize_scorecard,
    validate_scorecard_json,
)


# --- Helpers ---


def _make_category_score(category: str = "market", score: int = 7) -> CategoryScore:
    """Helper to create a CategoryScore for testing."""
    reasoning = (
        "This is a detailed reasoning paragraph that explains the score "
        "given to this category. It covers the key strengths and weaknesses "
        "found in the pitch deck content for the evaluated dimension."
    )
    return CategoryScore(
        category=category,
        score=score,
        reasoning=reasoning,
        suggestions=["Improve this specific area with concrete actions."],
    )


def _make_scorecard(**overrides) -> Scorecard:
    """Helper to create a valid Scorecard for testing."""
    defaults = {
        "id": uuid4(),
        "analysis_id": uuid4(),
        "deck_id": uuid4(),
        "overall_score": 7,
        "category_scores": [
            _make_category_score("market", 8),
            _make_category_score("team", 7),
            _make_category_score("business_model", 6),
            _make_category_score("competition", 7),
        ],
        "verdict_summary": (
            "This pitch deck demonstrates strong market understanding and a capable team. "
            "The business model shows promise but needs further clarification on unit economics. "
            "Competitive positioning is solid with clear differentiation strategies identified."
        ),
        "category_ranking": ["market", "team", "competition", "business_model"],
        "failed_categories": [],
        "created_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return Scorecard(**defaults)


def _make_serialized_scorecard(**overrides) -> dict:
    """Helper to create a valid serialized scorecard dict for testing."""
    scorecard = _make_scorecard(**overrides)
    return serialize_scorecard(scorecard)


# --- Tests for serialize_scorecard (Req 16.1) ---


class TestSerializeScorecard:
    """Tests for scorecard serialization. Validates Requirement 16.1."""

    def test_serialize_produces_dict(self):
        """Serialization produces a JSON-compatible dict."""
        scorecard = _make_scorecard()
        result = serialize_scorecard(scorecard)
        assert isinstance(result, dict)

    def test_uuid_fields_are_strings(self):
        """UUID fields are serialized as strings."""
        scorecard = _make_scorecard()
        result = serialize_scorecard(scorecard)
        assert isinstance(result["id"], str)
        assert isinstance(result["analysis_id"], str)
        assert isinstance(result["deck_id"], str)

    def test_uuid_values_preserved(self):
        """UUID string values match the original UUIDs."""
        sc_id = uuid4()
        analysis_id = uuid4()
        deck_id = uuid4()
        scorecard = _make_scorecard(id=sc_id, analysis_id=analysis_id, deck_id=deck_id)
        result = serialize_scorecard(scorecard)
        assert result["id"] == str(sc_id)
        assert result["analysis_id"] == str(analysis_id)
        assert result["deck_id"] == str(deck_id)

    def test_datetime_is_iso_string(self):
        """created_at is serialized as an ISO 8601 string."""
        scorecard = _make_scorecard()
        result = serialize_scorecard(scorecard)
        assert isinstance(result["created_at"], str)
        # Should be parseable back to datetime
        parsed = datetime.fromisoformat(result["created_at"])
        assert isinstance(parsed, datetime)

    def test_overall_score_preserved(self):
        """overall_score integer value is preserved."""
        scorecard = _make_scorecard(overall_score=9)
        result = serialize_scorecard(scorecard)
        assert result["overall_score"] == 9

    def test_category_scores_serialized(self):
        """category_scores list is serialized with all fields."""
        scorecard = _make_scorecard()
        result = serialize_scorecard(scorecard)
        assert isinstance(result["category_scores"], list)
        assert len(result["category_scores"]) == 4
        first = result["category_scores"][0]
        assert "category" in first
        assert "score" in first
        assert "reasoning" in first
        assert "suggestions" in first

    def test_verdict_summary_preserved(self):
        """verdict_summary string is preserved."""
        scorecard = _make_scorecard()
        result = serialize_scorecard(scorecard)
        assert result["verdict_summary"] == scorecard.verdict_summary

    def test_category_ranking_preserved(self):
        """category_ranking list is preserved."""
        ranking = ["team", "market", "competition", "business_model"]
        scorecard = _make_scorecard(category_ranking=ranking)
        result = serialize_scorecard(scorecard)
        assert result["category_ranking"] == ranking

    def test_failed_categories_preserved(self):
        """failed_categories list is preserved."""
        scorecard = _make_scorecard(failed_categories=["competition"])
        result = serialize_scorecard(scorecard)
        assert result["failed_categories"] == ["competition"]

    def test_empty_failed_categories(self):
        """Empty failed_categories list is preserved."""
        scorecard = _make_scorecard(failed_categories=[])
        result = serialize_scorecard(scorecard)
        assert result["failed_categories"] == []


# --- Tests for deserialize_scorecard (Req 16.2) ---


class TestDeserializeScorecard:
    """Tests for scorecard deserialization. Validates Requirement 16.2."""

    def test_deserialize_valid_json(self):
        """Valid JSON dict is deserialized into a Scorecard."""
        data = _make_serialized_scorecard()
        result = deserialize_scorecard(data)
        assert isinstance(result, Scorecard)

    def test_deserialize_preserves_all_fields(self):
        """Deserialization preserves all field values."""
        scorecard = _make_scorecard()
        data = serialize_scorecard(scorecard)
        result = deserialize_scorecard(data)

        assert result.id == scorecard.id
        assert result.analysis_id == scorecard.analysis_id
        assert result.deck_id == scorecard.deck_id
        assert result.overall_score == scorecard.overall_score
        assert result.verdict_summary == scorecard.verdict_summary
        assert result.category_ranking == scorecard.category_ranking
        assert result.failed_categories == scorecard.failed_categories

    def test_deserialize_preserves_category_scores(self):
        """Deserialization preserves category score details."""
        scorecard = _make_scorecard()
        data = serialize_scorecard(scorecard)
        result = deserialize_scorecard(data)

        assert len(result.category_scores) == len(scorecard.category_scores)
        for orig, deser in zip(scorecard.category_scores, result.category_scores):
            assert deser.category == orig.category
            assert deser.score == orig.score
            assert deser.reasoning == orig.reasoning
            assert deser.suggestions == orig.suggestions

    def test_deserialize_raises_on_missing_field(self):
        """Missing required field raises ScorecardValidationError."""
        data = _make_serialized_scorecard()
        del data["overall_score"]
        with pytest.raises(ScorecardValidationError) as exc_info:
            deserialize_scorecard(data)
        assert exc_info.value.field is not None

    def test_deserialize_raises_on_invalid_score(self):
        """Invalid score value raises ScorecardValidationError."""
        data = _make_serialized_scorecard()
        data["overall_score"] = 15  # Out of range
        with pytest.raises(ScorecardValidationError) as exc_info:
            deserialize_scorecard(data)
        assert "overall_score" in exc_info.value.field

    def test_deserialize_raises_on_invalid_uuid(self):
        """Invalid UUID string raises ScorecardValidationError."""
        data = _make_serialized_scorecard()
        data["id"] = "not-a-uuid"
        with pytest.raises(ScorecardValidationError):
            deserialize_scorecard(data)

    def test_deserialize_error_has_descriptive_message(self):
        """Error messages describe the problematic field."""
        data = _make_serialized_scorecard()
        data["overall_score"] = "not_a_number"
        with pytest.raises(ScorecardValidationError) as exc_info:
            deserialize_scorecard(data)
        assert "overall_score" in exc_info.value.message


# --- Tests for round-trip serialization (Req 16.3) ---


class TestRoundTrip:
    """Tests for serialize → deserialize round-trip. Validates Requirement 16.3."""

    def test_round_trip_preserves_equality(self):
        """serialize → deserialize produces equal Scorecard."""
        original = _make_scorecard()
        serialized = serialize_scorecard(original)
        deserialized = deserialize_scorecard(serialized)

        assert deserialized.id == original.id
        assert deserialized.analysis_id == original.analysis_id
        assert deserialized.deck_id == original.deck_id
        assert deserialized.overall_score == original.overall_score
        assert deserialized.verdict_summary == original.verdict_summary
        assert deserialized.category_ranking == original.category_ranking
        assert deserialized.failed_categories == original.failed_categories
        assert len(deserialized.category_scores) == len(original.category_scores)

    def test_round_trip_with_failed_categories(self):
        """Round-trip with failed categories preserves them."""
        original = _make_scorecard(
            category_scores=[_make_category_score("market", 8)],
            category_ranking=["market"],
            failed_categories=["team", "business_model", "competition"],
        )
        serialized = serialize_scorecard(original)
        deserialized = deserialize_scorecard(serialized)

        assert deserialized.failed_categories == ["team", "business_model", "competition"]

    def test_round_trip_with_boundary_scores(self):
        """Round-trip preserves boundary score values (1 and 10)."""
        original = _make_scorecard(
            overall_score=1,
            category_scores=[
                _make_category_score("market", 1),
                _make_category_score("team", 10),
            ],
            category_ranking=["team", "market"],
        )
        serialized = serialize_scorecard(original)
        deserialized = deserialize_scorecard(serialized)

        assert deserialized.overall_score == 1
        assert deserialized.category_scores[0].score == 1
        assert deserialized.category_scores[1].score == 10

    def test_round_trip_datetime_precision(self):
        """Round-trip preserves datetime to microsecond precision."""
        ts = datetime(2024, 6, 15, 10, 30, 45, 123456, tzinfo=timezone.utc)
        original = _make_scorecard(created_at=ts)
        serialized = serialize_scorecard(original)
        deserialized = deserialize_scorecard(serialized)

        assert deserialized.created_at == original.created_at

    def test_round_trip_multiple_suggestions(self):
        """Round-trip preserves multiple suggestions in category scores."""
        cs = CategoryScore(
            category="market",
            score=7,
            reasoning=(
                "The market analysis is thorough and well-researched with strong "
                "TAM/SAM/SOM figures that demonstrate significant upside potential."
            ),
            suggestions=[
                "Add international market expansion roadmap.",
                "Quantify customer acquisition cost projections.",
                "Include regulatory compliance analysis.",
            ],
        )
        original = _make_scorecard(
            category_scores=[cs],
            category_ranking=["market"],
        )
        serialized = serialize_scorecard(original)
        deserialized = deserialize_scorecard(serialized)

        assert deserialized.category_scores[0].suggestions == cs.suggestions


# --- Tests for validate_scorecard_json (Req 16.4, 16.5) ---


class TestValidateScorecardJson:
    """Tests for scorecard JSON validation. Validates Requirements 16.4, 16.5."""

    def test_valid_json_returns_scorecard(self):
        """Valid JSON passes validation and returns Scorecard."""
        data = _make_serialized_scorecard()
        result = validate_scorecard_json(data)
        assert isinstance(result, Scorecard)

    def test_rejects_non_dict_input(self):
        """Non-dict input raises ScorecardValidationError."""
        with pytest.raises(ScorecardValidationError) as exc_info:
            validate_scorecard_json("not a dict")  # type: ignore
        assert "JSON object" in exc_info.value.message or "dict" in exc_info.value.message

    def test_rejects_missing_id(self):
        """Missing 'id' field raises ScorecardValidationError."""
        data = _make_serialized_scorecard()
        del data["id"]
        with pytest.raises(ScorecardValidationError) as exc_info:
            validate_scorecard_json(data)
        assert "id" in exc_info.value.message

    def test_rejects_missing_analysis_id(self):
        """Missing 'analysis_id' field raises ScorecardValidationError."""
        data = _make_serialized_scorecard()
        del data["analysis_id"]
        with pytest.raises(ScorecardValidationError) as exc_info:
            validate_scorecard_json(data)
        assert "analysis_id" in exc_info.value.message

    def test_rejects_missing_overall_score(self):
        """Missing 'overall_score' field raises ScorecardValidationError."""
        data = _make_serialized_scorecard()
        del data["overall_score"]
        with pytest.raises(ScorecardValidationError) as exc_info:
            validate_scorecard_json(data)
        assert "overall_score" in exc_info.value.message

    def test_rejects_missing_category_scores(self):
        """Missing 'category_scores' field raises ScorecardValidationError."""
        data = _make_serialized_scorecard()
        del data["category_scores"]
        with pytest.raises(ScorecardValidationError) as exc_info:
            validate_scorecard_json(data)
        assert "category_scores" in exc_info.value.message

    def test_rejects_missing_verdict_summary(self):
        """Missing 'verdict_summary' field raises ScorecardValidationError."""
        data = _make_serialized_scorecard()
        del data["verdict_summary"]
        with pytest.raises(ScorecardValidationError) as exc_info:
            validate_scorecard_json(data)
        assert "verdict_summary" in exc_info.value.message

    def test_rejects_missing_created_at(self):
        """Missing 'created_at' field raises ScorecardValidationError."""
        data = _make_serialized_scorecard()
        del data["created_at"]
        with pytest.raises(ScorecardValidationError) as exc_info:
            validate_scorecard_json(data)
        assert "created_at" in exc_info.value.message

    def test_rejects_missing_category_ranking(self):
        """Missing 'category_ranking' raises ScorecardValidationError."""
        data = _make_serialized_scorecard()
        del data["category_ranking"]
        with pytest.raises(ScorecardValidationError) as exc_info:
            validate_scorecard_json(data)
        assert "category_ranking" in exc_info.value.message

    def test_rejects_missing_deck_id(self):
        """Missing 'deck_id' raises ScorecardValidationError."""
        data = _make_serialized_scorecard()
        del data["deck_id"]
        with pytest.raises(ScorecardValidationError) as exc_info:
            validate_scorecard_json(data)
        assert "deck_id" in exc_info.value.message

    def test_rejects_invalid_score_out_of_range(self):
        """Score out of range [1,10] raises ScorecardValidationError."""
        data = _make_serialized_scorecard()
        data["overall_score"] = 0
        with pytest.raises(ScorecardValidationError):
            validate_scorecard_json(data)

    def test_rejects_score_above_max(self):
        """Score above 10 raises ScorecardValidationError."""
        data = _make_serialized_scorecard()
        data["overall_score"] = 11
        with pytest.raises(ScorecardValidationError):
            validate_scorecard_json(data)

    def test_rejects_invalid_category_score_value(self):
        """Invalid category score value raises ScorecardValidationError."""
        data = _make_serialized_scorecard()
        data["category_scores"][0]["score"] = 0
        with pytest.raises(ScorecardValidationError):
            validate_scorecard_json(data)

    def test_error_identifies_problematic_field(self):
        """Error message identifies which field is problematic (Req 16.4)."""
        data = _make_serialized_scorecard()
        data["overall_score"] = "invalid"
        with pytest.raises(ScorecardValidationError) as exc_info:
            validate_scorecard_json(data)
        err = exc_info.value
        assert err.field is not None
        assert err.message is not None
        assert len(err.message) > 0

    def test_multiple_missing_fields_reports_first(self):
        """Multiple missing fields reports the first missing one."""
        data = _make_serialized_scorecard()
        del data["id"]
        del data["analysis_id"]
        del data["overall_score"]
        with pytest.raises(ScorecardValidationError) as exc_info:
            validate_scorecard_json(data)
        # Should list all missing fields in message
        assert "id" in exc_info.value.message

    def test_rejects_short_verdict_summary(self):
        """Verdict summary below 100 chars raises ScorecardValidationError."""
        data = _make_serialized_scorecard()
        data["verdict_summary"] = "Too short."
        with pytest.raises(ScorecardValidationError):
            validate_scorecard_json(data)

    def test_rejects_short_reasoning(self):
        """Category reasoning below 50 chars raises ScorecardValidationError."""
        data = _make_serialized_scorecard()
        data["category_scores"][0]["reasoning"] = "Too short."
        with pytest.raises(ScorecardValidationError):
            validate_scorecard_json(data)

    def test_rejects_empty_suggestions_list(self):
        """Empty suggestions list raises ScorecardValidationError."""
        data = _make_serialized_scorecard()
        data["category_scores"][0]["suggestions"] = []
        with pytest.raises(ScorecardValidationError):
            validate_scorecard_json(data)


# --- Tests for ScorecardValidationError ---


class TestScorecardValidationError:
    """Tests for the custom exception."""

    def test_error_has_field_and_message(self):
        """Error stores field and message attributes."""
        err = ScorecardValidationError(message="test error", field="test_field")
        assert err.field == "test_field"
        assert err.message == "test error"
        assert str(err) == "test error"

    def test_error_field_can_be_none(self):
        """Error field can be None for non-field-specific errors."""
        err = ScorecardValidationError(message="general error")
        assert err.field is None
        assert err.message == "general error"

    def test_error_is_exception(self):
        """ScorecardValidationError is an Exception subclass."""
        err = ScorecardValidationError(message="test")
        assert isinstance(err, Exception)
