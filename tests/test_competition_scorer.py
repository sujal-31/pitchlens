"""Unit tests for the Competition Scorer Agent."""

import pytest
from uuid import uuid4
from unittest.mock import patch, MagicMock

from app.models.schemas import CategoryScore, ExtractedContent, ExtractedSection
from app.agents.competition_scorer import (
    score_competition,
    _extract_competition_content,
    _identify_missing_dimensions,
    _build_missing_dimensions_instruction,
    _parse_llm_response,
    _build_fallback_score,
    NO_COMPETITION_INFO_RESPONSE,
    COMPETITION_DIMENSIONS,
)


# --- Test Data Fixtures ---


def _make_extracted_content(sections=None, warnings=None):
    """Helper to create ExtractedContent with given sections."""
    return ExtractedContent(
        deck_id=uuid4(),
        sections=sections or [],
        warnings=warnings or [],
        total_pages=10,
        pages_processed=10,
    )


def _make_competition_section(content: str, page_numbers=None):
    """Helper to create a competition ExtractedSection."""
    return ExtractedSection(
        category="competition",
        content=content,
        page_numbers=page_numbers or [1],
    )


# --- Tests for _extract_competition_content ---


class TestExtractCompetitionContent:
    def test_returns_empty_string_when_no_sections(self):
        ec = _make_extracted_content(sections=[])
        assert _extract_competition_content(ec) == ""

    def test_returns_empty_string_when_no_competition_sections(self):
        sections = [
            ExtractedSection(category="market", content="Market info", page_numbers=[1]),
            ExtractedSection(category="team", content="Team info", page_numbers=[2]),
        ]
        ec = _make_extracted_content(sections=sections)
        assert _extract_competition_content(ec) == ""

    def test_returns_competition_content_only(self):
        sections = [
            ExtractedSection(category="market", content="Market info", page_numbers=[1]),
            _make_competition_section("Our competitors include X and Y."),
            ExtractedSection(category="team", content="Team info", page_numbers=[3]),
        ]
        ec = _make_extracted_content(sections=sections)
        result = _extract_competition_content(ec)
        assert result == "Our competitors include X and Y."
        assert "Market info" not in result
        assert "Team info" not in result

    def test_concatenates_multiple_competition_sections(self):
        sections = [
            _make_competition_section("First competition section.", [1]),
            _make_competition_section("Second competition section.", [2]),
        ]
        ec = _make_extracted_content(sections=sections)
        result = _extract_competition_content(ec)
        assert "First competition section." in result
        assert "Second competition section." in result


# --- Tests for _identify_missing_dimensions ---


class TestIdentifyMissingDimensions:
    def test_all_dimensions_missing_for_empty_content(self):
        missing = _identify_missing_dimensions("")
        assert len(missing) == 3
        assert "competitive landscape awareness" in missing
        assert "differentiation" in missing
        assert "defensibility" in missing

    def test_landscape_present_when_competitor_mentioned(self):
        content = "Our main competitors are Startup X and Enterprise Y."
        missing = _identify_missing_dimensions(content)
        assert "competitive landscape awareness" not in missing

    def test_differentiation_present_when_unique_mentioned(self):
        content = "Our unique approach uses AI to solve this differently."
        missing = _identify_missing_dimensions(content)
        assert "differentiation" not in missing

    def test_defensibility_present_when_moat_mentioned(self):
        content = "We have a strong moat with patents and network effects."
        missing = _identify_missing_dimensions(content)
        assert "defensibility" not in missing

    def test_all_dimensions_present(self):
        content = (
            "Our competitors include X and Y. "
            "Our unique advantage is proprietary AI. "
            "We have built a moat through network effects and patents."
        )
        missing = _identify_missing_dimensions(content)
        assert missing == []

    def test_partial_coverage_two_present(self):
        content = "We have competitors in the space. Our unique value is speed."
        missing = _identify_missing_dimensions(content)
        assert "defensibility" in missing
        assert "competitive landscape awareness" not in missing
        assert "differentiation" not in missing


# --- Tests for _build_missing_dimensions_instruction ---


class TestBuildMissingDimensionsInstruction:
    def test_empty_when_no_missing(self):
        result = _build_missing_dimensions_instruction([])
        assert result == ""

    def test_contains_missing_dimension_names(self):
        result = _build_missing_dimensions_instruction(["differentiation", "defensibility"])
        assert "differentiation" in result
        assert "defensibility" in result
        assert "IMPORTANT" in result


# --- Tests for _parse_llm_response ---


class TestParseLlmResponse:
    def test_parses_valid_json(self):
        response = '{"score": 7, "reasoning": "' + ("Good competitive analysis. " * 10) + '", "suggestions": ["Add more detail"]}'
        result = _parse_llm_response(response)
        assert result is not None
        assert result.category == "competition"
        assert result.score == 7
        assert len(result.suggestions) == 1

    def test_parses_json_in_markdown_code_block(self):
        reasoning = "The deck demonstrates strong competitive awareness with clear identification of key players. " * 3
        response = f'```json\n{{"score": 8, "reasoning": "{reasoning.strip()}", "suggestions": ["Improve moat description"]}}\n```'
        result = _parse_llm_response(response)
        assert result is not None
        assert result.score == 8

    def test_returns_none_for_invalid_json(self):
        result = _parse_llm_response("This is not JSON at all")
        assert result is None

    def test_returns_none_for_missing_fields(self):
        result = _parse_llm_response('{"score": 5}')
        assert result is None

    def test_returns_none_for_score_out_of_range(self):
        response = '{"score": 11, "reasoning": "' + ("x " * 30) + '", "suggestions": ["Fix it"]}'
        result = _parse_llm_response(response)
        assert result is None

    def test_returns_none_for_empty_suggestions(self):
        response = '{"score": 5, "reasoning": "' + ("x " * 30) + '", "suggestions": []}'
        result = _parse_llm_response(response)
        assert result is None


# --- Tests for score_competition with missing info ---


class TestScoreCompetitionNoInfo:
    def test_returns_score_1_when_no_competition_sections(self):
        """Requirement 7.4: No competition info -> score=1."""
        sections = [
            ExtractedSection(category="market", content="Market info", page_numbers=[1]),
        ]
        ec = _make_extracted_content(sections=sections)
        result = score_competition(ec)
        assert result.category == "competition"
        assert result.score == 1
        assert "missing" in result.reasoning.lower()

    def test_returns_score_1_when_empty_competition_content(self):
        """Requirement 7.4: Empty competition content -> score=1."""
        sections = [
            _make_competition_section("   "),  # whitespace only
        ]
        ec = _make_extracted_content(sections=sections)
        result = score_competition(ec)
        assert result.score == 1

    def test_no_info_response_has_valid_schema(self):
        """Ensure the static NO_COMPETITION_INFO_RESPONSE meets all constraints."""
        assert NO_COMPETITION_INFO_RESPONSE.category == "competition"
        assert NO_COMPETITION_INFO_RESPONSE.score == 1
        assert len(NO_COMPETITION_INFO_RESPONSE.reasoning) >= 50
        assert len(NO_COMPETITION_INFO_RESPONSE.reasoning) <= 500
        assert 1 <= len(NO_COMPETITION_INFO_RESPONSE.suggestions) <= 3
        # Verify it mentions missing info
        assert "missing" in NO_COMPETITION_INFO_RESPONSE.reasoning.lower() or \
               "no" in NO_COMPETITION_INFO_RESPONSE.reasoning.lower()


# --- Tests for _build_fallback_score ---


class TestBuildFallbackScore:
    def test_returns_no_info_response_when_all_dimensions_missing(self):
        result = _build_fallback_score("", COMPETITION_DIMENSIONS.copy())
        assert result.score == 1

    def test_partial_coverage_produces_valid_score(self):
        """Requirement 7.5: Partial info with fewer than 3 dimensions."""
        result = _build_fallback_score(
            "We have competitors",
            ["differentiation", "defensibility"],
        )
        assert 2 <= result.score <= 5
        assert result.category == "competition"
        assert len(result.reasoning) >= 50
        assert 1 <= len(result.suggestions) <= 3

    def test_partial_notes_missing_dimensions(self):
        """Requirement 7.5: Note which dimensions are missing."""
        result = _build_fallback_score(
            "Some content",
            ["defensibility"],
        )
        assert "defensibility" in result.reasoning.lower()

    def test_suggestions_reference_missing_dimensions(self):
        result = _build_fallback_score(
            "Content here",
            ["competitive landscape awareness", "defensibility"],
        )
        suggestions_text = " ".join(result.suggestions).lower()
        assert "competitive" in suggestions_text or "landscape" in suggestions_text
        assert "moat" in suggestions_text or "barrier" in suggestions_text or "defensib" in suggestions_text


# --- Tests for score_competition with LLM (mocked) ---


class TestScoreCompetitionWithLLM:
    @patch("app.agents.competition_scorer.Crew")
    def test_successful_scoring_returns_valid_category_score(self, mock_crew_class):
        """Requirement 7.1, 7.2, 7.3: Successful scoring produces valid output."""
        reasoning = (
            "The deck demonstrates strong competitive landscape awareness by identifying "
            "three direct competitors and positioning the startup relative to each. "
            "Differentiation is clearly articulated through proprietary AI technology "
            "and unique data partnerships. However, defensibility could be stronger "
            "as the deck lacks discussion of patents or network effects that would "
            "create lasting barriers to entry."
        )
        mock_result = MagicMock()
        mock_result.__str__ = lambda self: (
            f'{{"score": 7, "reasoning": "{reasoning}", '
            f'"suggestions": ["Add patent portfolio details", "Describe network effects"]}}'
        )
        mock_crew_instance = MagicMock()
        mock_crew_instance.kickoff.return_value = mock_result
        mock_crew_class.return_value = mock_crew_instance

        sections = [
            _make_competition_section(
                "Our competitors include Startup X and Enterprise Y. "
                "Our unique advantage is our proprietary AI engine. "
                "We have built a moat through exclusive data partnerships."
            ),
        ]
        ec = _make_extracted_content(sections=sections)
        result = score_competition(ec)

        assert result.category == "competition"
        assert 1 <= result.score <= 10
        assert len(result.reasoning) >= 50
        assert 1 <= len(result.suggestions) <= 3

    @patch("app.agents.competition_scorer.Crew")
    def test_crew_exception_returns_fallback(self, mock_crew_class):
        """Agent failure produces fallback score, not an exception."""
        mock_crew_instance = MagicMock()
        mock_crew_instance.kickoff.side_effect = Exception("LLM timeout")
        mock_crew_class.return_value = mock_crew_instance

        sections = [
            _make_competition_section(
                "We have several competitors in the space."
            ),
        ]
        ec = _make_extracted_content(sections=sections)
        result = score_competition(ec)

        # Should return a valid fallback, not raise
        assert result.category == "competition"
        assert 1 <= result.score <= 10
        assert len(result.reasoning) >= 50
        assert 1 <= len(result.suggestions) <= 3

    @patch("app.agents.competition_scorer.Crew")
    def test_unparseable_response_returns_fallback(self, mock_crew_class):
        """Unparseable LLM output returns a fallback score."""
        mock_result = MagicMock()
        mock_result.__str__ = lambda self: "I cannot provide JSON right now."
        mock_crew_instance = MagicMock()
        mock_crew_instance.kickoff.return_value = mock_result
        mock_crew_class.return_value = mock_crew_instance

        sections = [
            _make_competition_section(
                "Our competitors are numerous. We have a unique value proposition."
            ),
        ]
        ec = _make_extracted_content(sections=sections)
        result = score_competition(ec)

        assert result.category == "competition"
        assert 1 <= result.score <= 10
