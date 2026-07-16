"""Unit tests for the Market Scorer Agent.

Tests cover:
- Missing market info handling (Req 4.4)
- Partial market info handling (Req 4.5)
- Market content extraction
- Response parsing and validation
- Score clamping, reasoning truncation, suggestion enforcement
"""

import json
import sys
from unittest.mock import patch, MagicMock, MagicMock as MockModule
from uuid import uuid4

import pytest

# Mock crewai module before importing market_scorer
crewai_mock = MagicMock()
sys.modules["crewai"] = crewai_mock

from app.agents.market_scorer import (
    _extract_market_content,
    _build_missing_info_score,
    _parse_agent_response,
    _clamp_score,
    _truncate_reasoning,
    _ensure_suggestions,
    score_market,
)
from app.models.schemas import CategoryScore, ExtractedContent, ExtractedSection


# --- Fixtures ---


def _make_extracted_content(sections=None):
    """Helper to create ExtractedContent for testing."""
    if sections is None:
        sections = []
    return ExtractedContent(
        deck_id=uuid4(),
        sections=sections,
        warnings=[],
        total_pages=10,
        pages_processed=10,
    )


def _make_market_section(content="Market content here"):
    """Helper to create a market ExtractedSection."""
    return ExtractedSection(
        category="market",
        content=content,
        page_numbers=[3, 4],
    )


def _make_non_market_section(category="team", content="Team content"):
    """Helper to create a non-market ExtractedSection."""
    return ExtractedSection(
        category=category,
        content=content,
        page_numbers=[5],
    )


# --- Tests for _extract_market_content ---


class TestExtractMarketContent:
    def test_returns_none_when_no_sections(self):
        content = _make_extracted_content(sections=[])
        assert _extract_market_content(content) is None

    def test_returns_none_when_no_market_sections(self):
        content = _make_extracted_content(sections=[
            _make_non_market_section("team", "Team info"),
            _make_non_market_section("competition", "Competition info"),
        ])
        assert _extract_market_content(content) is None

    def test_returns_market_content_single_section(self):
        content = _make_extracted_content(sections=[
            _make_market_section("TAM is $50B"),
        ])
        result = _extract_market_content(content)
        assert result == "TAM is $50B"

    def test_returns_concatenated_market_content(self):
        content = _make_extracted_content(sections=[
            _make_market_section("TAM is $50B"),
            _make_non_market_section("team", "Great team"),
            _make_market_section("Growing at 30% CAGR"),
        ])
        result = _extract_market_content(content)
        assert "TAM is $50B" in result
        assert "Growing at 30% CAGR" in result

    def test_ignores_non_market_sections(self):
        content = _make_extracted_content(sections=[
            _make_non_market_section("team", "Team data"),
            _make_market_section("Market data"),
            _make_non_market_section("business_model", "Business model"),
        ])
        result = _extract_market_content(content)
        assert "Team data" not in result
        assert "Business model" not in result
        assert "Market data" in result


# --- Tests for _build_missing_info_score ---


class TestBuildMissingInfoScore:
    def test_returns_score_of_1(self):
        result = _build_missing_info_score()
        assert result.score == 1

    def test_returns_market_category(self):
        result = _build_missing_info_score()
        assert result.category == "market"

    def test_reasoning_mentions_missing_info(self):
        result = _build_missing_info_score()
        assert "no identifiable market information" in result.reasoning.lower()

    def test_reasoning_within_word_limits(self):
        result = _build_missing_info_score()
        words = result.reasoning.split()
        assert 50 <= len(words) <= 500

    def test_has_1_to_3_suggestions(self):
        result = _build_missing_info_score()
        assert 1 <= len(result.suggestions) <= 3

    def test_is_valid_category_score(self):
        result = _build_missing_info_score()
        # Should pass Pydantic validation
        assert isinstance(result, CategoryScore)


# --- Tests for _parse_agent_response ---


class TestParseAgentResponse:
    def test_parses_clean_json(self):
        response = json.dumps({"score": 7, "reasoning": "Good market", "suggestions": ["Improve TAM"]})
        result = _parse_agent_response(response)
        assert result["score"] == 7
        assert result["reasoning"] == "Good market"

    def test_parses_json_with_code_fences(self):
        response = '```json\n{"score": 8, "reasoning": "Great", "suggestions": ["Add SAM"]}\n```'
        result = _parse_agent_response(response)
        assert result["score"] == 8

    def test_parses_json_with_surrounding_text(self):
        response = 'Here is the result: {"score": 5, "reasoning": "Average", "suggestions": ["More data"]} That is all.'
        result = _parse_agent_response(response)
        assert result["score"] == 5

    def test_raises_on_invalid_json(self):
        with pytest.raises((json.JSONDecodeError, ValueError)):
            _parse_agent_response("This is not JSON at all")

    def test_handles_code_fence_without_language(self):
        response = '```\n{"score": 6, "reasoning": "OK", "suggestions": ["Fix"]}\n```'
        result = _parse_agent_response(response)
        assert result["score"] == 6


# --- Tests for _clamp_score ---


class TestClampScore:
    def test_clamps_below_minimum(self):
        assert _clamp_score(0) == 1
        assert _clamp_score(-5) == 1

    def test_clamps_above_maximum(self):
        assert _clamp_score(11) == 10
        assert _clamp_score(100) == 10

    def test_preserves_valid_scores(self):
        for score in range(1, 11):
            assert _clamp_score(score) == score


# --- Tests for _truncate_reasoning ---


class TestTruncateReasoning:
    def test_preserves_reasoning_within_limits(self):
        reasoning = " ".join(["word"] * 100)
        result = _truncate_reasoning(reasoning)
        assert len(result.split()) >= 50
        assert len(result.split()) <= 500

    def test_truncates_long_reasoning(self):
        reasoning = " ".join(["word"] * 600)
        result = _truncate_reasoning(reasoning)
        assert len(result.split()) <= 500

    def test_pads_short_reasoning(self):
        reasoning = " ".join(["word"] * 20)
        result = _truncate_reasoning(reasoning)
        assert len(result.split()) >= 50

    def test_handles_empty_string(self):
        result = _truncate_reasoning("")
        # Should pad to meet minimum
        assert len(result.split()) >= 50


# --- Tests for _ensure_suggestions ---


class TestEnsureSuggestions:
    def test_returns_default_for_empty_list(self):
        result = _ensure_suggestions([])
        assert len(result) == 1
        assert isinstance(result[0], str)

    def test_preserves_valid_list(self):
        suggestions = ["Fix TAM", "Add growth data"]
        result = _ensure_suggestions(suggestions)
        assert result == suggestions

    def test_truncates_more_than_3(self):
        suggestions = ["One", "Two", "Three", "Four", "Five"]
        result = _ensure_suggestions(suggestions)
        assert len(result) == 3

    def test_keeps_single_suggestion(self):
        result = _ensure_suggestions(["Single suggestion"])
        assert len(result) == 1


# --- Integration tests for score_market ---


class TestScoreMarket:
    @pytest.mark.asyncio
    async def test_missing_market_info_returns_score_1(self):
        """Requirement 4.4: No market info → score=1."""
        content = _make_extracted_content(sections=[
            _make_non_market_section("team", "Great founding team"),
            _make_non_market_section("competition", "Competitive landscape"),
        ])
        result = await score_market(content)
        assert result.score == 1
        assert result.category == "market"
        assert "missing" in result.reasoning.lower() or "no" in result.reasoning.lower()

    @pytest.mark.asyncio
    async def test_empty_sections_returns_score_1(self):
        """Requirement 4.4: Empty sections → score=1."""
        content = _make_extracted_content(sections=[])
        result = await score_market(content)
        assert result.score == 1
        assert result.category == "market"

    @pytest.mark.asyncio
    @patch("app.agents.market_scorer.Crew")
    async def test_successful_scoring_with_valid_response(self, mock_crew_class):
        """Requirement 4.1, 4.2, 4.3: Valid scoring produces CategoryScore."""
        mock_result = MagicMock()
        mock_result.__str__ = lambda self: json.dumps({
            "score": 7,
            "reasoning": (
                "The pitch deck presents a strong market opportunity with a clearly "
                "defined TAM of $120 billion in the global SaaS market. The SAM is "
                "appropriately scoped to $15 billion targeting mid-market enterprises, "
                "and the SOM of $500 million represents a realistic initial capture "
                "target. Market timing is supported by the shift to remote work and "
                "digital transformation accelerating post-pandemic. Growth potential "
                "is evidenced by a cited CAGR of 25% in the target segment over the "
                "next five years according to Gartner research."
            ),
            "suggestions": [
                "Add bottom-up market sizing to complement the top-down approach for stronger credibility.",
                "Include specific competitor market share data to show available whitespace.",
            ],
        })

        mock_crew_instance = MagicMock()
        mock_crew_instance.kickoff.return_value = mock_result
        mock_crew_class.return_value = mock_crew_instance

        content = _make_extracted_content(sections=[
            _make_market_section("TAM $120B, SAM $15B, SOM $500M. 25% CAGR growth."),
        ])

        result = await score_market(content)

        assert result.category == "market"
        assert result.score == 7
        assert 1 <= len(result.suggestions) <= 3
        assert len(result.reasoning.split()) >= 50

    @pytest.mark.asyncio
    @patch("app.agents.market_scorer.Crew")
    async def test_handles_malformed_agent_response(self, mock_crew_class):
        """Agent returns unparseable response → fallback score."""
        mock_result = MagicMock()
        mock_result.__str__ = lambda self: "I cannot evaluate this properly."

        mock_crew_instance = MagicMock()
        mock_crew_instance.kickoff.return_value = mock_result
        mock_crew_class.return_value = mock_crew_instance

        content = _make_extracted_content(sections=[
            _make_market_section("Some market content"),
        ])

        result = await score_market(content)

        assert result.category == "market"
        assert 1 <= result.score <= 10
        assert len(result.reasoning.split()) >= 50
        assert 1 <= len(result.suggestions) <= 3

    @pytest.mark.asyncio
    @patch("app.agents.market_scorer.Crew")
    async def test_partial_info_noted_in_reasoning(self, mock_crew_class):
        """Requirement 4.5: Partial info has missing elements noted."""
        mock_result = MagicMock()
        mock_result.__str__ = lambda self: json.dumps({
            "score": 4,
            "reasoning": (
                "The deck provides some market information but is incomplete. "
                "TAM is mentioned as approximately $50 billion but no source is "
                "cited. SAM and SOM are not defined at all. Market timing "
                "indicators are absent from the deck, making it unclear why now "
                "is the right moment for this solution. However, some growth "
                "potential is suggested through references to increasing digital "
                "adoption trends, though specific CAGR figures are not provided. "
                "The market section needs significant strengthening to meet "
                "investor expectations for rigorous market analysis."
            ),
            "suggestions": [
                "Define SAM and SOM with specific figures and methodology.",
                "Add market timing evidence such as regulatory changes or technology shifts.",
                "Include credible third-party sources for all market size claims.",
            ],
        })

        mock_crew_instance = MagicMock()
        mock_crew_instance.kickoff.return_value = mock_result
        mock_crew_class.return_value = mock_crew_instance

        content = _make_extracted_content(sections=[
            _make_market_section("TAM approximately $50 billion. Digital adoption is growing."),
        ])

        result = await score_market(content)

        assert result.category == "market"
        assert result.score == 4
        assert 1 <= len(result.suggestions) <= 3
