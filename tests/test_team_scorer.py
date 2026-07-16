"""Unit tests for the Team Scorer Agent.

Tests cover:
- Missing team info handling (Req 5.4)
- Partial team info handling (Req 5.5)
- Content extraction from ExtractedContent
- Score validation and constraints
- Output parsing logic
"""

import json
import sys
from unittest.mock import patch, MagicMock, MagicMock as Mock
from uuid import uuid4

import pytest

# Mock crewai module if not available (Python version compatibility)
if "crewai" not in sys.modules:
    crewai_mock = MagicMock()
    sys.modules["crewai"] = crewai_mock

from app.models.schemas import CategoryScore, ExtractedContent, ExtractedSection
from app.agents.team_scorer import (
    _extract_team_content,
    _build_missing_team_score,
    _parse_agent_output,
    _validate_and_build_score,
    score_team,
)


# --- Fixtures ---


def make_extracted_content(sections=None, total_pages=10, pages_processed=10):
    """Helper to create ExtractedContent with given sections."""
    if sections is None:
        sections = []
    return ExtractedContent(
        deck_id=uuid4(),
        sections=sections,
        warnings=[],
        total_pages=total_pages,
        pages_processed=pages_processed,
    )


def make_team_section(content, page_numbers=None):
    """Helper to create a team ExtractedSection."""
    return ExtractedSection(
        category="team",
        content=content,
        page_numbers=page_numbers or [1],
    )


def make_non_team_section(content, category="market"):
    """Helper to create a non-team section."""
    return ExtractedSection(
        category=category,
        content=content,
        page_numbers=[1],
    )


# --- Tests for _extract_team_content ---


class TestExtractTeamContent:
    def test_no_sections_returns_empty(self):
        content = make_extracted_content(sections=[])
        assert _extract_team_content(content) == ""

    def test_no_team_sections_returns_empty(self):
        content = make_extracted_content(sections=[
            make_non_team_section("Market is growing fast", "market"),
            make_non_team_section("Revenue model is SaaS", "business_model"),
        ])
        assert _extract_team_content(content) == ""

    def test_single_team_section(self):
        team_text = "John Doe, CEO - 10 years fintech experience"
        content = make_extracted_content(sections=[
            make_team_section(team_text, [3]),
        ])
        result = _extract_team_content(content)
        assert "John Doe" in result
        assert "Page(s) 3" in result

    def test_multiple_team_sections_concatenated(self):
        content = make_extracted_content(sections=[
            make_team_section("John Doe, CEO", [1]),
            make_team_section("Jane Smith, CTO", [2]),
        ])
        result = _extract_team_content(content)
        assert "John Doe" in result
        assert "Jane Smith" in result

    def test_filters_only_team_category(self):
        content = make_extracted_content(sections=[
            make_non_team_section("Market info", "market"),
            make_team_section("Team info", [3]),
            make_non_team_section("Business model", "business_model"),
        ])
        result = _extract_team_content(content)
        assert "Team info" in result
        assert "Market info" not in result
        assert "Business model" not in result


# --- Tests for _build_missing_team_score ---


class TestBuildMissingTeamScore:
    def test_returns_score_of_1(self):
        score = _build_missing_team_score()
        assert score.score == 1

    def test_category_is_team(self):
        score = _build_missing_team_score()
        assert score.category == "team"

    def test_reasoning_mentions_missing(self):
        score = _build_missing_team_score()
        assert "no identifiable team information" in score.reasoning.lower() or \
               "missing" in score.reasoning.lower()

    def test_reasoning_meets_length_requirement(self):
        score = _build_missing_team_score()
        assert len(score.reasoning) >= 50
        assert len(score.reasoning) <= 500

    def test_suggestions_between_1_and_3(self):
        score = _build_missing_team_score()
        assert 1 <= len(score.suggestions) <= 3

    def test_validates_as_category_score(self):
        """Ensure the output is a valid CategoryScore."""
        score = _build_missing_team_score()
        # Re-validate via Pydantic
        validated = CategoryScore.model_validate(score.model_dump())
        assert validated.score == 1
        assert validated.category == "team"


# --- Tests for _parse_agent_output ---


class TestParseAgentOutput:
    def test_valid_json(self):
        data = {"category": "team", "score": 7, "reasoning": "Good team", "suggestions": ["Hire more"]}
        result = _parse_agent_output(json.dumps(data))
        assert result == data

    def test_json_with_markdown_code_block(self):
        data = {"category": "team", "score": 5, "reasoning": "Decent", "suggestions": ["Improve"]}
        text = f"```json\n{json.dumps(data)}\n```"
        result = _parse_agent_output(text)
        assert result == data

    def test_json_with_plain_code_block(self):
        data = {"category": "team", "score": 8, "reasoning": "Strong", "suggestions": ["Keep going"]}
        text = f"```\n{json.dumps(data)}\n```"
        result = _parse_agent_output(text)
        assert result == data

    def test_invalid_json_returns_none(self):
        result = _parse_agent_output("This is not JSON at all")
        assert result is None

    def test_empty_string_returns_none(self):
        result = _parse_agent_output("")
        assert result is None


# --- Tests for _validate_and_build_score ---


class TestValidateAndBuildScore:
    def test_valid_data_produces_score(self):
        data = {
            "score": 7,
            "reasoning": "The team has strong backgrounds with relevant experience in the domain. " * 3,
            "suggestions": ["Add a CTO with deep technical expertise in AI/ML."],
        }
        result = _validate_and_build_score(data, has_partial_info=False)
        assert result.category == "team"
        assert result.score == 7
        assert len(result.suggestions) == 1

    def test_score_clamped_to_minimum_1(self):
        data = {"score": -5, "reasoning": "x" * 60, "suggestions": ["Fix it"]}
        result = _validate_and_build_score(data, has_partial_info=False)
        assert result.score == 1

    def test_score_clamped_to_maximum_10(self):
        data = {"score": 15, "reasoning": "x" * 60, "suggestions": ["Fix it"]}
        result = _validate_and_build_score(data, has_partial_info=False)
        assert result.score == 10

    def test_partial_info_bumps_score_to_minimum_2(self):
        """Requirement 5.5: partial info should score 2-10."""
        data = {"score": 1, "reasoning": "x" * 60, "suggestions": ["Add more"]}
        result = _validate_and_build_score(data, has_partial_info=True)
        assert result.score == 2

    def test_partial_info_doesnt_affect_higher_scores(self):
        data = {"score": 5, "reasoning": "x" * 60, "suggestions": ["Improve"]}
        result = _validate_and_build_score(data, has_partial_info=True)
        assert result.score == 5

    def test_short_reasoning_gets_padded(self):
        data = {"score": 5, "reasoning": "Short.", "suggestions": ["Do more"]}
        result = _validate_and_build_score(data, has_partial_info=False)
        assert len(result.reasoning) >= 50

    def test_long_reasoning_gets_truncated(self):
        data = {"score": 5, "reasoning": "x" * 600, "suggestions": ["Fix"]}
        result = _validate_and_build_score(data, has_partial_info=False)
        assert len(result.reasoning) <= 500

    def test_empty_suggestions_gets_default(self):
        data = {"score": 5, "reasoning": "x" * 60, "suggestions": []}
        result = _validate_and_build_score(data, has_partial_info=False)
        assert len(result.suggestions) >= 1

    def test_more_than_3_suggestions_capped(self):
        data = {
            "score": 5,
            "reasoning": "x" * 60,
            "suggestions": ["a", "b", "c", "d", "e"],
        }
        result = _validate_and_build_score(data, has_partial_info=False)
        assert len(result.suggestions) == 3


# --- Tests for score_team (integration with mock) ---


class TestScoreTeam:
    def test_no_team_content_returns_score_1(self):
        """Requirement 5.4: No team info → score=1."""
        content = make_extracted_content(sections=[
            make_non_team_section("Market is large"),
        ])
        result = score_team(content)
        assert result.score == 1
        assert result.category == "team"

    def test_empty_sections_returns_score_1(self):
        """Requirement 5.4: No team info → score=1."""
        content = make_extracted_content(sections=[])
        result = score_team(content)
        assert result.score == 1
        assert result.category == "team"

    @patch("app.agents.team_scorer.Crew")
    def test_successful_scoring_with_full_team_info(self, mock_crew_class):
        """Test that valid LLM output produces correct CategoryScore."""
        mock_result = MagicMock()
        mock_result.__str__ = lambda _: json.dumps({
            "category": "team",
            "score": 8,
            "reasoning": (
                "The founding team demonstrates strong relevant experience with a "
                "combined 25 years in the fintech industry. The CEO previously founded "
                "and exited a payments company, while the CTO built scalable systems at "
                "a major bank. Team completeness is good with key technical and business "
                "roles filled. Domain expertise is clearly evident."
            ),
            "suggestions": [
                "Consider adding a dedicated sales/BD leader with enterprise fintech relationships.",
                "Highlight any advisory board members who could strengthen investor confidence."
            ]
        })
        mock_crew_instance = MagicMock()
        mock_crew_instance.kickoff.return_value = mock_result
        mock_crew_class.return_value = mock_crew_instance

        content = make_extracted_content(sections=[
            make_team_section(
                "John Doe, CEO - Founded and sold PayFast in 2019. 15 years fintech. "
                "Jane Smith, CTO - Former VP Engineering at BigBank. Built systems serving 10M users. "
                "Mike Johnson, CPO - Product leader at two fintech unicorns.",
                [4, 5]
            ),
        ])

        result = score_team(content)
        assert result.category == "team"
        assert result.score == 8
        assert len(result.suggestions) == 2

    @patch("app.agents.team_scorer.Crew")
    def test_partial_team_info_scores_above_1(self, mock_crew_class):
        """Requirement 5.5: Partial info → score 2-10."""
        mock_result = MagicMock()
        mock_result.__str__ = lambda _: json.dumps({
            "category": "team",
            "score": 4,
            "reasoning": (
                "The deck mentions two founders but provides minimal background details. "
                "Names and titles are given but no prior experience, education, or "
                "achievements are listed. Team completeness cannot be assessed as role "
                "descriptions are absent. The partial information suggests a small team "
                "but lacks the depth investors need to evaluate execution capability."
            ),
            "suggestions": [
                "Add detailed backgrounds for each founder including prior relevant roles and achievements.",
                "Specify each team member's unique contribution and how their skills complement each other."
            ]
        })
        mock_crew_instance = MagicMock()
        mock_crew_instance.kickoff.return_value = mock_result
        mock_crew_class.return_value = mock_crew_instance

        # Short content = partial info
        content = make_extracted_content(sections=[
            make_team_section("John - CEO, Jane - CTO", [3]),
        ])

        result = score_team(content)
        assert result.category == "team"
        assert 2 <= result.score <= 10  # Req 5.5

    @patch("app.agents.team_scorer.Crew")
    def test_crew_execution_error_returns_fallback(self, mock_crew_class):
        """Test graceful error handling when crew execution fails."""
        mock_crew_instance = MagicMock()
        mock_crew_instance.kickoff.side_effect = RuntimeError("LLM unavailable")
        mock_crew_class.return_value = mock_crew_instance

        content = make_extracted_content(sections=[
            make_team_section(
                "Full team section with lots of content about founders and their experience " * 10,
                [4, 5]
            ),
        ])

        result = score_team(content)
        # Should return a valid fallback score, not crash
        assert result.category == "team"
        assert 1 <= result.score <= 10
        assert len(result.reasoning) >= 50
        assert 1 <= len(result.suggestions) <= 3

    @patch("app.agents.team_scorer.Crew")
    def test_unparseable_output_with_partial_info(self, mock_crew_class):
        """Test fallback when LLM returns non-JSON with partial content."""
        mock_result = MagicMock()
        mock_result.__str__ = lambda _: "I think the team is okay but here's my thoughts..."
        mock_crew_instance = MagicMock()
        mock_crew_instance.kickoff.return_value = mock_result
        mock_crew_class.return_value = mock_crew_instance

        # Short content = partial info
        content = make_extracted_content(sections=[
            make_team_section("John - Founder", [2]),
        ])

        result = score_team(content)
        assert result.category == "team"
        assert result.score == 3  # Partial info fallback
        assert len(result.reasoning) >= 50

    @patch("app.agents.team_scorer.Crew")
    def test_unparseable_output_with_full_info(self, mock_crew_class):
        """Test fallback when LLM returns non-JSON with full content."""
        mock_result = MagicMock()
        mock_result.__str__ = lambda _: "Great team overall, very impressive backgrounds."
        mock_crew_instance = MagicMock()
        mock_crew_instance.kickoff.return_value = mock_result
        mock_crew_class.return_value = mock_crew_instance

        content = make_extracted_content(sections=[
            make_team_section(
                "John Doe, CEO with 15 years fintech. Jane Smith, CTO from Google. "
                "Full team of 8 engineers, designers, and sales professionals. " * 5,
                [3, 4, 5]
            ),
        ])

        result = score_team(content)
        assert result.category == "team"
        assert result.score == 5  # Full info fallback
        assert len(result.reasoning) >= 50

    def test_output_always_valid_category_score(self):
        """All outputs from score_team should be valid CategoryScore instances."""
        # Test with no content
        content = make_extracted_content(sections=[])
        result = score_team(content)

        # Validate it passes Pydantic validation
        validated = CategoryScore.model_validate(result.model_dump())
        assert validated.category == "team"
        assert 1 <= validated.score <= 10
        assert len(validated.reasoning) >= 50
        assert len(validated.reasoning) <= 500
        assert 1 <= len(validated.suggestions) <= 3
