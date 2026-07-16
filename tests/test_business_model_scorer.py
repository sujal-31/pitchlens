"""Unit tests for the Business Model Scorer Agent.

Tests cover:
- Missing business model info handling (score=1) - Requirement 6.4
- Partial business model info handling - Requirement 6.5
- Content extraction logic
- Output parsing and validation
- Timeout handling - Requirement 6.1
"""

import asyncio
import json
import sys
from unittest.mock import patch, MagicMock, MagicMock as MockModule
from uuid import uuid4

import pytest

# Mock crewai module before importing the agent module (crewai requires Python <=3.13)
mock_crewai = MagicMock()
mock_crewai.Agent = MagicMock
mock_crewai.Task = MagicMock
mock_crewai.Crew = MagicMock
sys.modules["crewai"] = mock_crewai

from app.models.schemas import CategoryScore, ExtractedContent, ExtractedSection
from app.agents.business_model_scorer import (
    CATEGORY,
    _extract_business_model_content,
    _build_missing_info_score,
    _parse_agent_output,
    _validate_and_build_score,
    score_business_model,
    score_business_model_sync,
)


# --- Fixtures ---


def make_extracted_content(sections=None, warnings=None):
    """Helper to create ExtractedContent with given sections."""
    return ExtractedContent(
        deck_id=uuid4(),
        sections=sections or [],
        warnings=warnings or [],
        total_pages=10,
        pages_processed=10,
    )


def make_section(category, content, page_numbers=None):
    """Helper to create an ExtractedSection."""
    return ExtractedSection(
        category=category,
        content=content,
        page_numbers=page_numbers or [1],
    )


# --- Test: Content Extraction ---


class TestExtractBusinessModelContent:
    def test_extracts_business_model_sections(self):
        sections = [
            make_section("market", "Market info here"),
            make_section("business_model", "Revenue from subscriptions at $99/month"),
            make_section("business_model", "Unit economics: CAC $50, LTV $500"),
            make_section("team", "Team info here"),
        ]
        extracted = make_extracted_content(sections)
        content = _extract_business_model_content(extracted)

        assert "Revenue from subscriptions" in content
        assert "Unit economics" in content
        assert "Market info here" not in content
        assert "Team info here" not in content

    def test_returns_empty_when_no_sections(self):
        extracted = make_extracted_content([])
        content = _extract_business_model_content(extracted)
        assert content == ""

    def test_falls_back_to_uncategorized_when_no_business_model(self):
        sections = [
            make_section("market", "Market data"),
            make_section("uncategorized", "Some pricing details might be here"),
        ]
        extracted = make_extracted_content(sections)
        content = _extract_business_model_content(extracted)

        assert "Some pricing details" in content

    def test_prefers_business_model_over_uncategorized(self):
        sections = [
            make_section("business_model", "SaaS model with monthly subscriptions"),
            make_section("uncategorized", "Random content"),
        ]
        extracted = make_extracted_content(sections)
        content = _extract_business_model_content(extracted)

        assert "SaaS model" in content
        assert "Random content" not in content

    def test_includes_page_numbers_in_output(self):
        sections = [
            make_section("business_model", "Revenue details", [3, 4]),
        ]
        extracted = make_extracted_content(sections)
        content = _extract_business_model_content(extracted)

        assert "Page 3, 4" in content


# --- Test: Missing Info Score ---


class TestBuildMissingInfoScore:
    def test_returns_score_of_1(self):
        score = _build_missing_info_score()
        assert score.score == 1

    def test_category_is_business_model(self):
        score = _build_missing_info_score()
        assert score.category == CATEGORY

    def test_reasoning_mentions_missing_info(self):
        score = _build_missing_info_score()
        assert "no identifiable business model information" in score.reasoning.lower()

    def test_has_valid_suggestions(self):
        score = _build_missing_info_score()
        assert 1 <= len(score.suggestions) <= 3

    def test_reasoning_meets_length_requirement(self):
        score = _build_missing_info_score()
        assert len(score.reasoning) >= 50
        assert len(score.reasoning) <= 500

    def test_validates_as_category_score(self):
        """Ensure the missing info score passes Pydantic validation."""
        score = _build_missing_info_score()
        # Re-validate through model
        validated = CategoryScore.model_validate(score.model_dump())
        assert validated.score == 1


# --- Test: Output Parsing ---


class TestParseAgentOutput:
    def test_parses_clean_json(self):
        output = json.dumps({
            "score": 7,
            "reasoning": "Good business model",
            "suggestions": ["Add more detail on unit economics"],
        })
        result = _parse_agent_output(output)
        assert result["score"] == 7
        assert result["reasoning"] == "Good business model"

    def test_parses_json_with_surrounding_text(self):
        output = 'Here is my analysis:\n{"score": 5, "reasoning": "Average model", "suggestions": ["Improve pricing"]}\nDone.'
        result = _parse_agent_output(output)
        assert result["score"] == 5

    def test_raises_on_invalid_json(self):
        with pytest.raises(ValueError, match="Could not parse"):
            _parse_agent_output("This is not JSON at all")

    def test_parses_json_with_newlines_inside(self):
        output = '{"score": 8, "reasoning": "Line one.\\nLine two.", "suggestions": ["Suggestion"]}'
        result = _parse_agent_output(output)
        assert result["score"] == 8


# --- Test: Validate and Build Score ---


class TestValidateAndBuildScore:
    def test_builds_valid_category_score(self):
        parsed = {
            "score": 7,
            "reasoning": "The business model shows a clear SaaS subscription approach with monthly recurring revenue. Unit economics are partially addressed with a stated CAC of $50.",
            "suggestions": ["Clarify LTV calculation", "Add scalability metrics"],
        }
        score = _validate_and_build_score(parsed)
        assert score.category == CATEGORY
        assert score.score == 7
        assert len(score.suggestions) == 2

    def test_clamps_score_above_10(self):
        parsed = {
            "score": 15,
            "reasoning": "x" * 60,
            "suggestions": ["Something"],
        }
        score = _validate_and_build_score(parsed)
        assert score.score == 10

    def test_clamps_score_below_1(self):
        parsed = {
            "score": -3,
            "reasoning": "x" * 60,
            "suggestions": ["Something"],
        }
        score = _validate_and_build_score(parsed)
        assert score.score == 1

    def test_pads_short_reasoning(self):
        parsed = {
            "score": 5,
            "reasoning": "Short.",
            "suggestions": ["Something"],
        }
        score = _validate_and_build_score(parsed)
        assert len(score.reasoning) >= 50

    def test_truncates_long_reasoning(self):
        parsed = {
            "score": 5,
            "reasoning": "x" * 600,
            "suggestions": ["Something"],
        }
        score = _validate_and_build_score(parsed)
        assert len(score.reasoning) <= 500

    def test_provides_default_suggestion_when_empty(self):
        parsed = {
            "score": 5,
            "reasoning": "x" * 60,
            "suggestions": [],
        }
        score = _validate_and_build_score(parsed)
        assert len(score.suggestions) >= 1

    def test_caps_suggestions_at_3(self):
        parsed = {
            "score": 5,
            "reasoning": "x" * 60,
            "suggestions": ["One", "Two", "Three", "Four", "Five"],
        }
        score = _validate_and_build_score(parsed)
        assert len(score.suggestions) == 3


# --- Test: Score Business Model (Integration with mock) ---


class TestScoreBusinessModelSync:
    @patch("app.agents.business_model_scorer.Crew")
    def test_returns_score_1_for_empty_content(self, mock_crew_class):
        """Requirement 6.4: No business model info → score=1."""
        extracted = make_extracted_content([])
        result = score_business_model_sync(extracted)

        assert result.score == 1
        assert result.category == CATEGORY
        assert "no identifiable business model" in result.reasoning.lower()
        # Crew should not be called when there's no content
        mock_crew_class.assert_not_called()

    @patch("app.agents.business_model_scorer.Crew")
    def test_returns_valid_score_for_business_model_content(self, mock_crew_class):
        """Requirement 6.1, 6.2, 6.3: Score with reasoning and suggestions."""
        mock_result = MagicMock()
        mock_result.__str__ = lambda self: json.dumps({
            "score": 7,
            "reasoning": (
                "The business model demonstrates a clear SaaS subscription approach "
                "with tiered pricing at $49, $99, and $199 monthly plans. Revenue model "
                "clarity is strong. Unit economics are partially addressed with customer "
                "acquisition cost mentioned but lifetime value not quantified. Scalability "
                "is implied through the platform nature but lacks specific growth mechanics."
            ),
            "suggestions": [
                "Quantify customer lifetime value and show LTV:CAC ratio",
                "Add specific scalability metrics like marginal cost per new customer",
            ],
        })
        mock_crew_instance = MagicMock()
        mock_crew_instance.kickoff.return_value = mock_result
        mock_crew_class.return_value = mock_crew_instance

        sections = [
            make_section("business_model", "SaaS pricing: $49/mo, $99/mo, $199/mo. CAC is $120."),
        ]
        extracted = make_extracted_content(sections)
        result = score_business_model_sync(extracted)

        assert result.score == 7
        assert result.category == CATEGORY
        assert len(result.reasoning) >= 50
        assert 1 <= len(result.suggestions) <= 3

    @patch("app.agents.business_model_scorer.Crew")
    def test_handles_partial_business_model_info(self, mock_crew_class):
        """Requirement 6.5: Partial info → score 2-10 noting missing factors."""
        mock_result = MagicMock()
        mock_result.__str__ = lambda self: json.dumps({
            "score": 4,
            "reasoning": (
                "The deck mentions a subscription revenue model but provides no unit "
                "economics data and does not address scalability. Revenue model clarity "
                "is moderate as pricing tiers are listed without justification. Unit "
                "economics are completely absent with no mention of CAC, LTV, or margins. "
                "Scalability factors are missing from the presentation entirely."
            ),
            "suggestions": [
                "Add unit economics slide showing CAC, LTV, and gross margins",
                "Include a scalability section explaining how growth reduces unit costs",
            ],
        })
        mock_crew_instance = MagicMock()
        mock_crew_instance.kickoff.return_value = mock_result
        mock_crew_class.return_value = mock_crew_instance

        sections = [
            make_section("business_model", "We charge $99/month for our platform."),
        ]
        extracted = make_extracted_content(sections)
        result = score_business_model_sync(extracted)

        assert 2 <= result.score <= 10
        assert result.category == CATEGORY


# --- Test: Async Score with Timeout ---


class TestScoreBusinessModelAsync:
    @pytest.mark.asyncio
    @patch("app.agents.business_model_scorer.Crew")
    async def test_returns_result_within_timeout(self, mock_crew_class):
        mock_result = MagicMock()
        mock_result.__str__ = lambda self: json.dumps({
            "score": 6,
            "reasoning": (
                "The business model section presents a freemium to paid conversion "
                "funnel with reasonable pricing. Revenue model is clear but unit "
                "economics need more detail. Scalability approach is mentioned but "
                "not fully substantiated with specific metrics or growth mechanics."
            ),
            "suggestions": ["Provide conversion rate benchmarks from freemium to paid"],
        })
        mock_crew_instance = MagicMock()
        mock_crew_instance.kickoff.return_value = mock_result
        mock_crew_class.return_value = mock_crew_instance

        sections = [make_section("business_model", "Freemium model with paid tiers")]
        extracted = make_extracted_content(sections)
        result = await score_business_model(extracted)

        assert result.score == 6
        assert result.category == CATEGORY

    @pytest.mark.asyncio
    async def test_returns_timeout_score_on_timeout(self):
        """Requirement 6.1: 30-second timeout produces valid fallback score."""
        sections = [make_section("business_model", "Some content")]
        extracted = make_extracted_content(sections)

        # Mock the sync function to sleep longer than timeout
        async def slow_executor(func, *args):
            await asyncio.sleep(35)
            return func(*args)

        with patch("app.agents.business_model_scorer.SCORING_TIMEOUT", 0.1):
            with patch("app.agents.business_model_scorer.Crew") as mock_crew_class:
                mock_crew_instance = MagicMock()
                # Make kickoff block for longer than timeout
                import time
                mock_crew_instance.kickoff.side_effect = lambda: time.sleep(1)
                mock_crew_class.return_value = mock_crew_instance

                result = await score_business_model(extracted)

        assert result.score == 1
        assert result.category == CATEGORY
        assert "timed out" in result.reasoning.lower()

    @pytest.mark.asyncio
    async def test_handles_parsing_error_gracefully(self):
        """Error handling: returns valid score even on parse failure."""
        sections = [make_section("business_model", "Some content")]
        extracted = make_extracted_content(sections)

        with patch("app.agents.business_model_scorer.Crew") as mock_crew_class:
            mock_result = MagicMock()
            mock_result.__str__ = lambda self: "Not valid JSON at all"
            mock_crew_instance = MagicMock()
            mock_crew_instance.kickoff.return_value = mock_result
            mock_crew_class.return_value = mock_crew_instance

            result = await score_business_model(extracted)

        assert result.score == 1
        assert result.category == CATEGORY
        assert len(result.reasoning) >= 50
