"""Unit tests for RAG Engine service.

Tests chunking logic, prompt building, citation extraction,
and session context management.
"""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.models.schemas import ChatResponse, ExtractedContent, ExtractedSection
from app.services.rag_engine import RAGEngine, CHUNK_TOKEN_TARGET, MAX_SESSION_MESSAGES


@pytest.fixture
def rag_engine():
    """Create a fresh RAGEngine instance for testing."""
    return RAGEngine()


@pytest.fixture
def sample_extracted_content():
    """Sample extracted content for testing."""
    return ExtractedContent(
        deck_id=uuid.uuid4(),
        sections=[
            ExtractedSection(
                category="market",
                content="The total addressable market for AI-powered analytics is $50 billion. "
                "The serviceable addressable market in North America is $15 billion. "
                "Market growth rate is projected at 25% CAGR through 2028. "
                "Key drivers include digital transformation and increased data volumes.",
                page_numbers=[1, 2],
            ),
            ExtractedSection(
                category="team",
                content="Our founding team has 30 years of combined experience. "
                "CEO Jane Smith previously founded two successful startups. "
                "CTO John Doe led engineering at a Fortune 500 company.",
                page_numbers=[3],
            ),
        ],
        total_pages=5,
        pages_processed=5,
    )


class TestChunkText:
    """Tests for the _chunk_text method."""

    def test_empty_text_returns_empty_list(self, rag_engine):
        """Empty or whitespace-only text produces no chunks."""
        assert rag_engine._chunk_text("", "market") == []
        assert rag_engine._chunk_text("   ", "market") == []

    def test_short_text_produces_single_chunk(self, rag_engine):
        """Text shorter than token target stays as one chunk."""
        short_text = "This is a short sentence about the market."
        chunks = rag_engine._chunk_text(short_text, "market")
        assert len(chunks) == 1
        assert chunks[0]["text"] == short_text
        assert chunks[0]["category"] == "market"

    def test_long_text_splits_into_multiple_chunks(self, rag_engine):
        """Text exceeding the token target is split into multiple chunks."""
        # Generate text that's well over 500 tokens
        sentences = [
            f"Sentence number {i} contains important market data about growth projections and revenue models."
            for i in range(50)
        ]
        long_text = " ".join(sentences)
        chunks = rag_engine._chunk_text(long_text, "market")
        assert len(chunks) > 1
        # Each chunk should not massively exceed target
        for chunk in chunks:
            word_count = len(chunk["text"].split())
            token_estimate = int(word_count * 1.3)
            # Allow some tolerance since we don't break mid-sentence
            assert token_estimate < CHUNK_TOKEN_TARGET * 2

    def test_preserves_section_category(self, rag_engine):
        """Each chunk retains the section category label."""
        text = "Some content about the team. More team information here."
        chunks = rag_engine._chunk_text(text, "team")
        for chunk in chunks:
            assert chunk["category"] == "team"

    def test_splits_on_sentence_boundaries(self, rag_engine):
        """Chunks split at sentence boundaries, not mid-sentence."""
        text = "First sentence. Second sentence. Third sentence."
        chunks = rag_engine._chunk_text(text, "market")
        # With short text, should be single chunk
        assert len(chunks) == 1
        assert "First sentence." in chunks[0]["text"]


class TestSplitSentences:
    """Tests for the _split_sentences helper method."""

    def test_splits_on_periods(self, rag_engine):
        """Splits text on period-space boundaries."""
        text = "First sentence. Second sentence. Third."
        sentences = rag_engine._split_sentences(text)
        assert len(sentences) == 3

    def test_splits_on_question_marks(self, rag_engine):
        """Splits on question mark boundaries."""
        text = "What is the market size? It is $50B. How fast is growth?"
        sentences = rag_engine._split_sentences(text)
        assert len(sentences) == 3

    def test_handles_empty_text(self, rag_engine):
        """Empty string returns empty list."""
        assert rag_engine._split_sentences("") == []


class TestBuildPrompt:
    """Tests for the _build_prompt method."""

    def test_includes_context_chunks(self, rag_engine):
        """Context chunks are formatted into the prompt."""
        chunks = [
            {"text": "Market is $50B", "category": "market", "similarity": 0.9},
        ]
        prompt = rag_engine._build_prompt(
            question="What is the market size?",
            context_chunks=chunks,
            scorecard_data="Overall Score: 7/10",
            conversation_history="No previous conversation.",
        )
        assert "[Section: market]" in prompt
        assert "Market is $50B" in prompt

    def test_includes_scorecard_data(self, rag_engine):
        """Scorecard data appears in the prompt."""
        prompt = rag_engine._build_prompt(
            question="What is the score?",
            context_chunks=[],
            scorecard_data="Overall Score: 8/10\nMarket Score: 7/10",
            conversation_history="No previous conversation.",
        )
        assert "Overall Score: 8/10" in prompt
        assert "Market Score: 7/10" in prompt

    def test_includes_conversation_history(self, rag_engine):
        """Conversation history is included in the prompt."""
        history = "User: Hello\nAssistant: Hi there"
        prompt = rag_engine._build_prompt(
            question="Follow up",
            context_chunks=[],
            scorecard_data="",
            conversation_history=history,
        )
        assert "User: Hello" in prompt
        assert "Assistant: Hi there" in prompt

    def test_empty_chunks_shows_no_content_message(self, rag_engine):
        """When no chunks are retrieved, a message indicates this."""
        prompt = rag_engine._build_prompt(
            question="Unrelated question",
            context_chunks=[],
            scorecard_data="",
            conversation_history="No previous conversation.",
        )
        assert "No relevant deck content found" in prompt


class TestExtractCitations:
    """Tests for the _extract_citations method."""

    def test_extracts_explicit_citations(self, rag_engine):
        """Finds [Section: X] patterns in response text."""
        response = "Based on [Section: market] data, the TAM is $50B."
        chunks = [{"text": "TAM is $50B", "category": "market", "similarity": 0.9}]
        citations = rag_engine._extract_citations(response, chunks)
        assert "market" in citations

    def test_multiple_citations(self, rag_engine):
        """Extracts multiple different citations."""
        response = (
            "The [Section: market] shows growth. "
            "The [Section: team] is experienced."
        )
        chunks = [
            {"text": "growth", "category": "market", "similarity": 0.9},
            {"text": "experienced", "category": "team", "similarity": 0.8},
        ]
        citations = rag_engine._extract_citations(response, chunks)
        assert "market" in citations
        assert "team" in citations

    def test_no_citations_falls_back_to_top_chunks(self, rag_engine):
        """When no explicit citations, uses top context chunk categories."""
        response = "The market is growing rapidly."
        chunks = [
            {"text": "growth data", "category": "market", "similarity": 0.9},
        ]
        citations = rag_engine._extract_citations(response, chunks)
        assert "market" in citations

    def test_empty_response_and_chunks(self, rag_engine):
        """Empty inputs produce no citations."""
        citations = rag_engine._extract_citations("", [])
        assert citations == []

    def test_deduplicates_citations(self, rag_engine):
        """Duplicate citations are deduplicated."""
        response = "[Section: market] shows TAM. [Section: market] shows SAM."
        chunks = [{"text": "data", "category": "market", "similarity": 0.9}]
        citations = rag_engine._extract_citations(response, chunks)
        assert citations.count("market") == 1


class TestGetSessionContext:
    """Tests for session context retrieval logic."""

    @pytest.mark.asyncio
    async def test_empty_session_returns_no_conversation(self, rag_engine):
        """Empty session returns 'No previous conversation' string."""
        mock_session = MagicMock()
        mock_session.id = uuid.uuid4()

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result

        history = await rag_engine._get_session_context(mock_session, mock_db)
        assert history == "No previous conversation."

    @pytest.mark.asyncio
    async def test_formats_messages_correctly(self, rag_engine):
        """Messages are formatted as 'Role: content'."""
        mock_session = MagicMock()
        mock_session.id = uuid.uuid4()

        msg1 = MagicMock()
        msg1.role = "user"
        msg1.content = "What is the market size?"
        msg1.created_at = datetime(2024, 1, 1, 10, 0, 0)

        msg2 = MagicMock()
        msg2.role = "assistant"
        msg2.content = "The market size is $50B."
        msg2.created_at = datetime(2024, 1, 1, 10, 0, 1)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        # Note: method queries desc and we reverse, so return in desc order
        mock_scalars.all.return_value = [msg2, msg1]
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result

        history = await rag_engine._get_session_context(mock_session, mock_db)
        assert "User: What is the market size?" in history
        assert "Assistant: The market size is $50B." in history


class TestQueryErrorHandling:
    """Tests for error handling in the query method."""

    @pytest.mark.asyncio
    async def test_returns_service_error_on_exception(self, rag_engine):
        """On internal error, returns service error without exposing details."""
        mock_db = AsyncMock()
        mock_db.execute.side_effect = Exception("Database connection failed")

        deck_id = uuid.uuid4()
        user_id = uuid.uuid4()

        result = await rag_engine.query(deck_id, user_id, "test question", mock_db)

        assert isinstance(result, ChatResponse)
        assert "unable to process" in result.response
        assert result.cited_sections == []
        # Must not expose internal error details (Req 11.5, 11.6)
        assert "Database" not in result.response
        assert "connection" not in result.response
