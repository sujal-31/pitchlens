"""Unit tests for the Verdict Aggregator Agent.

Tests cover:
- Overall score computation (Req 9.1, 9.5) - Property 3
- Category ranking sort order (Req 9.3) - Property 4
- Failed categories detection (Req 9.5)
- Verdict summary validation (Req 9.2)
- Full aggregation flow (Req 9.4)
"""

import sys
from unittest.mock import patch, MagicMock
from uuid import uuid4

import pytest

# Mock crewai module before importing verdict_aggregator
crewai_mock = MagicMock()
sys.modules["crewai"] = crewai_mock

from app.agents.verdict_aggregator import (
    ALL_CATEGORIES,
    compute_overall_score,
    compute_category_ranking,
    compute_failed_categories,
    _validate_verdict_summary,
    _build_fallback_verdict,
    aggregate_scores,
)
from app.models.schemas import CategoryScore, Scorecard


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


def _make_all_scores(
    market: int = 7,
    team: int = 8,
    business_model: int = 6,
    competition: int = 5,
) -> list:
    """Helper to create a full set of CategoryScores."""
    return [
        _make_category_score("market", market),
        _make_category_score("team", team),
        _make_category_score("business_model", business_model),
        _make_category_score("competition", competition),
    ]


# --- Tests for compute_overall_score ---


class TestComputeOverallScore:
    """Tests for overall score computation. Validates Requirement 9.1, 9.5."""

    def test_all_four_categories_mean(self):
        """Overall score is mean of all 4 scores rounded to nearest integer."""
        scores = _make_all_scores(market=7, team=8, business_model=6, competition=5)
        # Mean = (7+8+6+5)/4 = 26/4 = 6.5 → rounds to 6 (banker's rounding)
        result = compute_overall_score(scores)
        assert result == 6  # Python rounds 6.5 to 6 (banker's rounding)

    def test_all_same_scores(self):
        """When all scores are equal, overall equals that score."""
        scores = _make_all_scores(market=8, team=8, business_model=8, competition=8)
        assert compute_overall_score(scores) == 8

    def test_rounds_up(self):
        """Mean above .5 rounds up."""
        scores = _make_all_scores(market=7, team=8, business_model=7, competition=8)
        # Mean = 30/4 = 7.5 → rounds to 8 (banker's rounding)
        result = compute_overall_score(scores)
        assert result == 8

    def test_three_categories_partial(self):
        """With 3 categories, computes mean of 3."""
        scores = [
            _make_category_score("market", 9),
            _make_category_score("team", 6),
            _make_category_score("business_model", 3),
        ]
        # Mean = 18/3 = 6.0
        assert compute_overall_score(scores) == 6

    def test_two_categories_partial(self):
        """With 2 categories, computes mean of 2."""
        scores = [
            _make_category_score("market", 10),
            _make_category_score("team", 4),
        ]
        # Mean = 14/2 = 7.0
        assert compute_overall_score(scores) == 7

    def test_single_category(self):
        """With 1 category, overall equals that score."""
        scores = [_make_category_score("market", 3)]
        assert compute_overall_score(scores) == 3

    def test_empty_scores_returns_1(self):
        """Empty input returns minimum score of 1."""
        assert compute_overall_score([]) == 1

    def test_all_max_scores(self):
        """All 10s gives overall of 10."""
        scores = _make_all_scores(market=10, team=10, business_model=10, competition=10)
        assert compute_overall_score(scores) == 10

    def test_all_min_scores(self):
        """All 1s gives overall of 1."""
        scores = _make_all_scores(market=1, team=1, business_model=1, competition=1)
        assert compute_overall_score(scores) == 1

    def test_result_clamped_to_valid_range(self):
        """Result is always between 1 and 10."""
        for market in range(1, 11):
            for team in range(1, 11):
                scores = [
                    _make_category_score("market", market),
                    _make_category_score("team", team),
                ]
                result = compute_overall_score(scores)
                assert 1 <= result <= 10


# --- Tests for compute_category_ranking ---


class TestComputeCategoryRanking:
    """Tests for category ranking. Validates Requirement 9.3."""

    def test_descending_order(self):
        """Categories are ranked from highest to lowest score."""
        scores = _make_all_scores(market=7, team=9, business_model=5, competition=3)
        ranking = compute_category_ranking(scores)
        assert ranking == ["team", "market", "business_model", "competition"]

    def test_alphabetical_tie_break(self):
        """Tied scores are broken alphabetically."""
        scores = [
            _make_category_score("team", 7),
            _make_category_score("market", 7),
            _make_category_score("competition", 7),
            _make_category_score("business_model", 7),
        ]
        ranking = compute_category_ranking(scores)
        # All tied at 7, should be alphabetical
        assert ranking == ["business_model", "competition", "market", "team"]

    def test_partial_tie(self):
        """Mix of unique and tied scores."""
        scores = [
            _make_category_score("market", 8),
            _make_category_score("team", 8),
            _make_category_score("business_model", 5),
            _make_category_score("competition", 5),
        ]
        ranking = compute_category_ranking(scores)
        # 8s first (alphabetical: market, team), then 5s (alphabetical: business_model, competition)
        assert ranking == ["market", "team", "business_model", "competition"]

    def test_single_category(self):
        """Single category returns just that category."""
        scores = [_make_category_score("market", 6)]
        ranking = compute_category_ranking(scores)
        assert ranking == ["market"]

    def test_empty_scores(self):
        """Empty input returns empty list."""
        assert compute_category_ranking([]) == []

    def test_two_categories_different_scores(self):
        """Two categories ranked correctly."""
        scores = [
            _make_category_score("competition", 9),
            _make_category_score("market", 4),
        ]
        ranking = compute_category_ranking(scores)
        assert ranking == ["competition", "market"]


# --- Tests for compute_failed_categories ---


class TestComputeFailedCategories:
    """Tests for failed category detection. Validates Requirement 9.5."""

    def test_no_failed_when_all_present(self):
        """All 4 categories provided means no failures."""
        scores = _make_all_scores()
        assert compute_failed_categories(scores) == []

    def test_one_missing(self):
        """One category missing is listed as failed."""
        scores = [
            _make_category_score("market", 7),
            _make_category_score("team", 8),
            _make_category_score("business_model", 6),
        ]
        assert compute_failed_categories(scores) == ["competition"]

    def test_two_missing(self):
        """Two categories missing are both listed."""
        scores = [
            _make_category_score("market", 7),
            _make_category_score("competition", 5),
        ]
        failed = compute_failed_categories(scores)
        assert sorted(failed) == ["business_model", "team"]

    def test_three_missing(self):
        """Three categories missing."""
        scores = [_make_category_score("team", 8)]
        failed = compute_failed_categories(scores)
        assert sorted(failed) == ["business_model", "competition", "market"]

    def test_all_missing(self):
        """Empty scores means all categories failed."""
        failed = compute_failed_categories([])
        assert sorted(failed) == sorted(ALL_CATEGORIES)

    def test_failed_categories_sorted_alphabetically(self):
        """Failed categories are returned in alphabetical order."""
        scores = [_make_category_score("team", 5)]
        failed = compute_failed_categories(scores)
        assert failed == sorted(failed)


# --- Tests for _validate_verdict_summary ---


class TestValidateVerdictSummary:
    """Tests for verdict summary validation. Validates Requirement 9.2."""

    def test_preserves_valid_text(self):
        """Text within bounds is preserved."""
        text = "A" * 200
        result = _validate_verdict_summary(text)
        assert result == text

    def test_truncates_long_text(self):
        """Text over 500 chars is truncated."""
        text = "word " * 200  # Much longer than 500 chars
        result = _validate_verdict_summary(text)
        assert len(result) <= 500

    def test_pads_short_text(self):
        """Text under 100 chars is padded."""
        text = "Short verdict."
        result = _validate_verdict_summary(text)
        assert len(result) >= 100

    def test_removes_code_fences(self):
        """Markdown code fences are stripped."""
        text = "```\n" + "A" * 200 + "\n```"
        result = _validate_verdict_summary(text)
        assert "```" not in result

    def test_minimum_length_boundary(self):
        """Exactly 100 chars is valid."""
        text = "A" * 100
        result = _validate_verdict_summary(text)
        assert len(result) >= 100

    def test_maximum_length_boundary(self):
        """Exactly 500 chars is valid."""
        text = "A" * 500
        result = _validate_verdict_summary(text)
        assert len(result) <= 500


# --- Tests for _build_fallback_verdict ---


class TestBuildFallbackVerdict:
    """Tests for fallback verdict generation."""

    def test_fallback_with_scores(self):
        """Fallback with available scores produces valid text."""
        scores = _make_all_scores()
        result = _build_fallback_verdict(scores, [])
        assert 100 <= len(result) <= 500
        assert "overall score" in result.lower() or "overall" in result.lower()

    def test_fallback_with_no_scores(self):
        """Fallback with empty scores produces valid text."""
        result = _build_fallback_verdict([], ALL_CATEGORIES)
        assert 100 <= len(result) <= 500

    def test_fallback_mentions_failed_categories(self):
        """Fallback text mentions failed categories."""
        scores = [_make_category_score("market", 7)]
        failed = ["team", "business_model", "competition"]
        result = _build_fallback_verdict(scores, failed)
        assert "team" in result or "could not be evaluated" in result


# --- Integration tests for aggregate_scores ---


class TestAggregateScores:
    """Tests for the full aggregation flow. Validates Requirements 9.1-9.5."""

    @patch("app.agents.verdict_aggregator.Crew")
    def test_full_aggregation_all_categories(self, mock_crew_class):
        """Full aggregation with all 4 categories produces valid Scorecard."""
        mock_result = MagicMock()
        mock_result.__str__ = lambda self: (
            "This pitch deck demonstrates strong potential with an overall "
            "score reflecting solid fundamentals across all evaluated dimensions. "
            "The team dimension stands out as the strongest area, suggesting "
            "experienced founders with relevant backgrounds. Market opportunity "
            "is well articulated with clear TAM/SAM/SOM figures. The business "
            "model shows room for improvement in unit economics clarity. "
            "Competition analysis is the weakest area, needing more specific "
            "differentiation and defensibility arguments to convince investors."
        )

        mock_crew_instance = MagicMock()
        mock_crew_instance.kickoff.return_value = mock_result
        mock_crew_class.return_value = mock_crew_instance

        scores = _make_all_scores(market=7, team=9, business_model=6, competition=4)
        analysis_id = uuid4()
        deck_id = uuid4()

        result = aggregate_scores(scores, analysis_id, deck_id)

        assert isinstance(result, Scorecard)
        assert result.analysis_id == analysis_id
        assert result.deck_id == deck_id
        # Mean = (7+9+6+4)/4 = 26/4 = 6.5 → 6 (banker's rounding)
        assert result.overall_score == 6
        assert result.category_ranking == ["team", "market", "business_model", "competition"]
        assert result.failed_categories == []
        assert len(result.category_scores) == 4
        assert 100 <= len(result.verdict_summary) <= 500

    @patch("app.agents.verdict_aggregator.Crew")
    def test_partial_aggregation_missing_categories(self, mock_crew_class):
        """Partial aggregation with 2 categories tracks failures."""
        mock_result = MagicMock()
        mock_result.__str__ = lambda self: (
            "This is a partial evaluation of the pitch deck due to scoring "
            "failures in some categories. Based on available scores, the deck "
            "shows moderate potential. The market opportunity is reasonably well "
            "defined, and the team has relevant backgrounds. However, without "
            "business model and competition evaluations, a complete picture "
            "cannot be formed. Founders should address the gaps to receive a "
            "full investor-grade assessment of their pitch materials."
        )

        mock_crew_instance = MagicMock()
        mock_crew_instance.kickoff.return_value = mock_result
        mock_crew_class.return_value = mock_crew_instance

        scores = [
            _make_category_score("market", 7),
            _make_category_score("team", 8),
        ]
        analysis_id = uuid4()
        deck_id = uuid4()

        result = aggregate_scores(scores, analysis_id, deck_id)

        assert isinstance(result, Scorecard)
        # Mean = (7+8)/2 = 7.5 → 8 (banker's rounding)
        assert result.overall_score == 8
        assert result.category_ranking == ["team", "market"]
        assert sorted(result.failed_categories) == ["business_model", "competition"]
        assert len(result.category_scores) == 2

    @patch("app.agents.verdict_aggregator.Crew")
    def test_crew_failure_uses_fallback_verdict(self, mock_crew_class):
        """When CrewAI fails, fallback verdict is used."""
        mock_crew_instance = MagicMock()
        mock_crew_instance.kickoff.side_effect = RuntimeError("LLM unavailable")
        mock_crew_class.return_value = mock_crew_instance

        scores = _make_all_scores(market=5, team=5, business_model=5, competition=5)
        analysis_id = uuid4()
        deck_id = uuid4()

        result = aggregate_scores(scores, analysis_id, deck_id)

        assert isinstance(result, Scorecard)
        assert result.overall_score == 5
        assert 100 <= len(result.verdict_summary) <= 500
        assert result.failed_categories == []

    @patch("app.agents.verdict_aggregator.Crew")
    def test_single_category_aggregation(self, mock_crew_class):
        """Single category score produces valid scorecard."""
        mock_result = MagicMock()
        mock_result.__str__ = lambda self: (
            "This is a severely limited evaluation with only one category "
            "scored successfully. The market opportunity received a moderate "
            "score indicating some potential but significant gaps in the "
            "presentation. Three out of four evaluation categories failed, "
            "which means a comprehensive assessment is not possible at this "
            "time. A full re-evaluation is recommended to get complete feedback."
        )

        mock_crew_instance = MagicMock()
        mock_crew_instance.kickoff.return_value = mock_result
        mock_crew_class.return_value = mock_crew_instance

        scores = [_make_category_score("market", 6)]
        analysis_id = uuid4()
        deck_id = uuid4()

        result = aggregate_scores(scores, analysis_id, deck_id)

        assert isinstance(result, Scorecard)
        assert result.overall_score == 6
        assert result.category_ranking == ["market"]
        assert sorted(result.failed_categories) == ["business_model", "competition", "team"]

    @patch("app.agents.verdict_aggregator.Crew")
    def test_scorecard_has_all_required_fields(self, mock_crew_class):
        """Scorecard contains all required fields per Requirement 9.4."""
        mock_result = MagicMock()
        mock_result.__str__ = lambda self: (
            "The pitch deck shows a balanced performance across all four "
            "evaluation dimensions. Market opportunity is well defined with "
            "clear sizing. The team is experienced and complete. Business model "
            "demonstrates clear revenue pathways. Competitive positioning is "
            "reasonably articulated. Overall this represents a solid early-stage "
            "pitch that would benefit from deeper competitive moat arguments."
        )

        mock_crew_instance = MagicMock()
        mock_crew_instance.kickoff.return_value = mock_result
        mock_crew_class.return_value = mock_crew_instance

        scores = _make_all_scores()
        result = aggregate_scores(scores, uuid4(), uuid4())

        # Verify all required fields are present (Req 9.4)
        assert result.id is not None
        assert result.analysis_id is not None
        assert result.deck_id is not None
        assert 1 <= result.overall_score <= 10
        assert len(result.category_scores) > 0
        assert 100 <= len(result.verdict_summary) <= 500
        assert len(result.category_ranking) > 0
        assert isinstance(result.failed_categories, list)
        assert result.created_at is not None
