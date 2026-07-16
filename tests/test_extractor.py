"""Unit tests for the Extractor Agent.

Tests PDF parsing, section detection, category mapping, partial extraction
warnings, corruption handling, and timeout behavior.
"""

import io
import time
from unittest.mock import patch, MagicMock
from uuid import uuid4

import pytest
from PyPDF2 import PdfWriter

from app.agents.extractor import (
    extract_content,
    _is_heading,
    _classify_section,
    _split_page_into_sections,
    _merge_sections_by_category,
    get_extractor_agent_config,
    ExtractionError,
    ExtractionTimeoutError,
    EXTRACTION_TIMEOUT_SECONDS,
)
from app.models.schemas import ExtractedContent, ExtractedSection


# --- Helpers ---


def _create_pdf_bytes(pages: list[str]) -> bytes:
    """Create a valid PDF with given page texts."""
    writer = PdfWriter()
    for text in pages:
        # Create a page and add text using a basic approach
        # PyPDF2 PdfWriter doesn't directly support adding text to blank pages easily,
        # so we'll use the reader approach by creating a minimal PDF
        pass

    # Use a different approach: create PDF with reportlab-like content
    # Since we only have PyPDF2, we'll create a minimal valid PDF manually
    buf = io.BytesIO()
    writer = PdfWriter()
    for text in pages:
        writer.add_blank_page(width=612, height=792)
    writer.write(buf)
    return buf.getvalue()


def _create_pdf_with_text(pages: list[str]) -> bytes:
    """Create a PDF where extract_text() returns the given strings per page.

    Since PyPDF2's PdfWriter doesn't easily add text content, we mock at the
    reader level in tests that need specific text content.
    """
    # Create a minimal valid PDF structure
    writer = PdfWriter()
    for _ in pages:
        writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# --- Tests for _is_heading ---


class TestIsHeading:
    def test_all_caps_line(self):
        assert _is_heading("MARKET OPPORTUNITY") is True

    def test_numbered_section(self):
        assert _is_heading("1. Market Size") is True

    def test_short_title_like_line(self):
        assert _is_heading("Our Team") is True

    def test_long_sentence_not_heading(self):
        assert _is_heading(
            "This is a long sentence that describes the market opportunity in detail."
        ) is False

    def test_empty_string(self):
        assert _is_heading("") is False

    def test_single_char(self):
        assert _is_heading("A") is False

    def test_line_ending_with_period(self):
        # Sentences ending with punctuation are not headings
        assert _is_heading("Market size is growing.") is False

    def test_markdown_heading(self):
        assert _is_heading("# Market Opportunity") is True
        assert _is_heading("## Team") is True


# --- Tests for _classify_section ---


class TestClassifySection:
    def test_market_content(self):
        content = "The total addressable market (TAM) is $50B with strong growth rate."
        assert _classify_section(content) == "market"

    def test_team_content(self):
        content = "Our founding team has 20 years of combined experience. CEO Jane Smith."
        assert _classify_section(content) == "team"

    def test_business_model_content(self):
        content = "Revenue model is SaaS subscription with monthly pricing tiers."
        assert _classify_section(content) == "business_model"

    def test_competition_content(self):
        content = "Our main competitors include Company X. Our differentiation is speed."
        assert _classify_section(content) == "competition"

    def test_uncategorized_content(self):
        content = "Thank you for your time. Contact us at hello@startup.com."
        assert _classify_section(content) == "uncategorized"

    def test_heading_influences_classification(self):
        content = "We have several advantages in this space."
        assert _classify_section(content, heading="MARKET OPPORTUNITY") == "market"

    def test_empty_content(self):
        assert _classify_section("") == "uncategorized"


# --- Tests for _split_page_into_sections ---


class TestSplitPageIntoSections:
    def test_single_section_no_heading(self):
        text = "This is just plain content without any heading."
        sections = _split_page_into_sections(text, 1)
        assert len(sections) == 1
        assert sections[0][0] == ""  # no heading
        assert sections[0][2] == 1  # page number

    def test_multiple_sections(self):
        text = "MARKET OPPORTUNITY\nThe TAM is $50B.\nOUR TEAM\nJane is the CEO."
        sections = _split_page_into_sections(text, 2)
        assert len(sections) == 2
        assert sections[0][0] == "MARKET OPPORTUNITY"
        assert "TAM" in sections[0][1]
        assert sections[1][0] == "OUR TEAM"
        assert "Jane" in sections[1][1]

    def test_empty_text(self):
        sections = _split_page_into_sections("", 1)
        assert len(sections) == 0


# --- Tests for _merge_sections_by_category ---


class TestMergeSectionsByCategory:
    def test_merge_same_category(self):
        raw = [
            ("MARKET", "TAM is $50B", 1),
            ("MARKET GROWTH", "Growing at 20% CAGR in the market", 2),
        ]
        merged = _merge_sections_by_category(raw)
        # Both should be merged into market category
        market_sections = [s for s in merged if s.category == "market"]
        assert len(market_sections) == 1
        assert 1 in market_sections[0].page_numbers
        assert 2 in market_sections[0].page_numbers

    def test_different_categories(self):
        raw = [
            ("MARKET", "TAM is $50B in the market", 1),
            ("TEAM", "Our founder has 10 years experience in the team", 2),
        ]
        merged = _merge_sections_by_category(raw)
        categories = {s.category for s in merged}
        assert "market" in categories
        assert "team" in categories

    def test_empty_input(self):
        assert _merge_sections_by_category([]) == []


# --- Tests for extract_content ---


class TestExtractContent:
    def test_corrupted_pdf(self):
        """Req 3.3: Corruption returns ExtractionError."""
        deck_id = uuid4()
        with pytest.raises(ExtractionError) as exc_info:
            extract_content(b"not a valid pdf", deck_id)
        assert "Failed to parse PDF" in exc_info.value.reason

    def test_valid_empty_pdf(self):
        """A valid PDF with blank pages produces warnings about no text."""
        deck_id = uuid4()
        pdf_bytes = _create_pdf_with_text(["", ""])
        result = extract_content(pdf_bytes, deck_id)
        assert result.deck_id == deck_id
        assert result.total_pages == 2
        assert result.pages_processed == 2
        # Should have warnings about pages with no text
        assert len(result.warnings) == 2
        assert any("no extractable text" in w for w in result.warnings)

    def test_timeout_produces_partial_results(self):
        """Req 3.5: On timeout, return partial results with warning."""
        deck_id = uuid4()
        # Create a PDF with many pages
        pdf_bytes = _create_pdf_with_text([""] * 10)

        # Use a very short timeout that should trigger immediately
        # We mock time.time to simulate timeout
        call_count = [0]
        real_time = time.time

        def fake_time():
            call_count[0] += 1
            if call_count[0] == 1:
                return 0.0  # start time
            # After first page, return value past timeout
            return 31.0

        with patch("app.agents.extractor.time.time", side_effect=fake_time):
            result = extract_content(pdf_bytes, deck_id, timeout_seconds=30)

        assert result.pages_processed < result.total_pages
        assert any("timed out" in w.lower() for w in result.warnings)

    def test_partial_extraction_warning_for_imageless_pages(self):
        """Req 3.2: Pages with no text get partial-extraction warning."""
        deck_id = uuid4()
        pdf_bytes = _create_pdf_with_text([""])

        result = extract_content(pdf_bytes, deck_id)
        assert any("no extractable text" in w for w in result.warnings)
        assert result.pages_processed == 1

    def test_returns_extracted_content_model(self):
        """Req 3.4: Returns ExtractedContent with sections mapped to categories."""
        deck_id = uuid4()
        pdf_bytes = _create_pdf_with_text(["page1"])

        # Mock the reader to return categorizable text
        mock_page = MagicMock()
        mock_page.extract_text.return_value = (
            "MARKET OPPORTUNITY\n"
            "The total addressable market is $50 billion.\n"
            "OUR TEAM\n"
            "Our founding team includes experienced leaders."
        )

        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]

        with patch("app.agents.extractor.PdfReader") as mock_pdf_reader:
            mock_pdf_reader.return_value = mock_reader
            result = extract_content(pdf_bytes, deck_id)

        assert isinstance(result, ExtractedContent)
        assert result.deck_id == deck_id
        assert result.total_pages == 1
        assert result.pages_processed == 1
        categories = {s.category for s in result.sections}
        assert "market" in categories
        assert "team" in categories


# --- Tests for CrewAI Agent Config ---


class TestExtractorAgentConfig:
    def test_config_has_required_fields(self):
        config = get_extractor_agent_config()
        assert "role" in config
        assert "goal" in config
        assert "backstory" in config
        assert "llm_config" in config

    def test_config_llm_reads_env(self):
        with patch.dict(
            "os.environ",
            {"LLM_API_KEY": "test-key", "LLM_BASE_URL": "http://test", "MODEL_ID": "test-model"},
        ):
            config = get_extractor_agent_config()
            assert config["llm_config"]["api_key"] == "test-key"
            assert config["llm_config"]["base_url"] == "http://test"
            assert config["llm_config"]["model"] == "test-model"
