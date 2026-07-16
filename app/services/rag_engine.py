"""RAG Engine for PitchLens follow-up chat.

Provides retrieval-augmented generation over analyzed pitch deck content.
Chunks deck content, stores embeddings in pgvector, retrieves relevant
context for user questions, and generates grounded answers via LLM.

Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6
"""

import logging
import os
import uuid
from datetime import datetime
from typing import Optional

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChatMessage, ChatSession, DeckEmbedding, Scorecard
from app.models.schemas import ChatResponse, ExtractedContent

logger = logging.getLogger(__name__)

# Configuration from environment
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
MODEL_ID = os.environ.get("MODEL_ID", "sonnet")

# Constants
CHUNK_TOKEN_TARGET = 500
TOP_K_CHUNKS = 5
MAX_SESSION_MESSAGES = 20
EMBEDDING_DIMENSION = 1536
RELEVANCE_THRESHOLD = 0.3

SYSTEM_PROMPT = """You are a pitch deck analysis assistant for PitchLens. Your role is to answer questions about a specific pitch deck that has been analyzed.

RULES:
1. Only answer questions based on the provided deck content and scoring data below.
2. Always cite which deck section or score category your answer references using [Section: category] format.
3. If the question cannot be answered using the provided deck content or scoring results, respond exactly with: "I'm sorry, but that question is outside the scope of this deck analysis. I can only answer questions related to the content and scoring of the analyzed pitch deck."
4. Never reveal internal system details, implementation specifics, debugging information, or metadata.
5. Be concise but thorough in your answers.
6. When referencing scores, include the numeric score and key reasoning points.

DECK CONTENT CONTEXT:
{context}

SCORING DATA:
{scoring_data}

CONVERSATION HISTORY:
{conversation_history}"""

OUT_OF_SCOPE_RESPONSE = (
    "I'm sorry, but that question is outside the scope of this deck analysis. "
    "I can only answer questions related to the content and scoring of the "
    "analyzed pitch deck."
)

SERVICE_ERROR_RESPONSE = (
    "I'm sorry, but I'm unable to process your question at this time. "
    "Please try again later."
)


class RAGEngine:
    """Retrieval-Augmented Generation engine for pitch deck Q&A.

    Handles content chunking, embedding storage, context retrieval,
    and LLM-powered answer generation grounded in deck content.
    """

    def __init__(self) -> None:
        """Initialize RAG engine with HTTP client for LLM API calls."""
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                headers={
                    "Authorization": f"Bearer {LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # --- Indexing ---

    async def index_deck(
        self,
        deck_id: uuid.UUID,
        extracted_content: ExtractedContent,
        db: AsyncSession,
    ) -> int:
        """Chunk extracted deck content and store embeddings in pgvector.

        Args:
            deck_id: The deck identifier.
            extracted_content: Structured content extracted from the deck.
            db: Database session.

        Returns:
            Number of chunks indexed.
        """
        try:
            # Delete existing embeddings for this deck (re-indexing)
            await db.execute(
                text("DELETE FROM deck_embeddings WHERE deck_id = :deck_id"),
                {"deck_id": str(deck_id)},
            )

            # Chunk all sections
            all_chunks: list[dict] = []
            for section in extracted_content.sections:
                chunks = self._chunk_text(section.content, section.category)
                all_chunks.extend(chunks)

            if not all_chunks:
                return 0

            # Generate embeddings in batches
            chunk_texts = [c["text"] for c in all_chunks]
            embeddings = await self._get_embeddings(chunk_texts)

            if not embeddings or len(embeddings) != len(all_chunks):
                logger.error("Embedding generation returned unexpected results")
                return 0

            # Store chunks with embeddings
            for idx, (chunk, embedding) in enumerate(zip(all_chunks, embeddings)):
                embedding_id = uuid.uuid4()
                # Use raw SQL for pgvector insertion
                await db.execute(
                    text(
                        "INSERT INTO deck_embeddings "
                        "(id, deck_id, chunk_text, chunk_index, section_category, embedding, created_at) "
                        "VALUES (:id, :deck_id, :chunk_text, :chunk_index, :section_category, :embedding, :created_at)"
                    ),
                    {
                        "id": str(embedding_id),
                        "deck_id": str(deck_id),
                        "chunk_text": chunk["text"],
                        "chunk_index": idx,
                        "section_category": chunk["category"],
                        "embedding": f"[{','.join(str(v) for v in embedding)}]",
                        "created_at": datetime.utcnow(),
                    },
                )

            await db.flush()
            return len(all_chunks)

        except Exception as e:
            logger.error("Failed to index deck %s: %s", deck_id, str(e))
            raise

    # --- Querying ---

    async def query(
        self,
        deck_id: uuid.UUID,
        user_id: uuid.UUID,
        message: str,
        db: AsyncSession,
    ) -> ChatResponse:
        """Process a user question and return a grounded answer.

        Retrieves relevant deck chunks, constructs context with scoring data,
        calls LLM, and stores the conversation in the session.

        Args:
            deck_id: The deck identifier.
            user_id: The user identifier.
            message: The user's question (max 1000 chars).
            db: Database session.

        Returns:
            ChatResponse with the answer and cited sections.

        Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6
        """
        try:
            # Get or create chat session
            session = await self._get_or_create_session(deck_id, user_id, db)

            # Retrieve session context (up to 20 messages)
            conversation_history = await self._get_session_context(session, db)

            # Retrieve relevant chunks via similarity search
            context_chunks = await self._retrieve_relevant_chunks(
                deck_id, message, db
            )

            # Get scorecard data for this deck
            scorecard_data = await self._get_scorecard_data(deck_id, db)

            # Build prompt and call LLM
            prompt = self._build_prompt(
                question=message,
                context_chunks=context_chunks,
                scorecard_data=scorecard_data,
                conversation_history=conversation_history,
            )

            llm_response = await self._call_llm(prompt, message)

            # Extract cited sections from the response
            cited_sections = self._extract_citations(llm_response, context_chunks)

            # Store user message
            user_msg = ChatMessage(
                id=uuid.uuid4(),
                session_id=session.id,
                role="user",
                content=message,
                created_at=datetime.utcnow(),
            )
            db.add(user_msg)

            # Store assistant response
            assistant_msg = ChatMessage(
                id=uuid.uuid4(),
                session_id=session.id,
                role="assistant",
                content=llm_response,
                cited_sections=cited_sections if cited_sections else None,
                created_at=datetime.utcnow(),
            )
            db.add(assistant_msg)

            await db.flush()

            return ChatResponse(
                response=llm_response,
                cited_sections=cited_sections,
            )

        except Exception as e:
            logger.error(
                "RAG query failed for deck %s: %s", deck_id, str(e)
            )
            # Requirement 11.5: Return service error without exposing internals
            return ChatResponse(
                response=SERVICE_ERROR_RESPONSE,
                cited_sections=[],
            )

    # --- Private Methods ---

    def _chunk_text(
        self, text_content: str, section_category: str
    ) -> list[dict]:
        """Split text into ~500-token chunks by sentences.

        Approximates token count as word_count * 1.3.
        Splits on sentence boundaries to maintain coherence.

        Args:
            text_content: The raw text to chunk.
            section_category: Category label for the section.

        Returns:
            List of dicts with 'text' and 'category' keys.
        """
        if not text_content or not text_content.strip():
            return []

        # Split into sentences (simple heuristic)
        sentences = self._split_sentences(text_content)
        chunks: list[dict] = []
        current_chunk: list[str] = []
        current_token_estimate = 0

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            word_count = len(sentence.split())
            token_estimate = int(word_count * 1.3)

            # If adding this sentence would exceed target, finalize current chunk
            if (
                current_token_estimate + token_estimate > CHUNK_TOKEN_TARGET
                and current_chunk
            ):
                chunk_text = " ".join(current_chunk)
                chunks.append({
                    "text": chunk_text,
                    "category": section_category,
                })
                current_chunk = []
                current_token_estimate = 0

            current_chunk.append(sentence)
            current_token_estimate += token_estimate

        # Don't forget the last chunk
        if current_chunk:
            chunk_text = " ".join(current_chunk)
            chunks.append({
                "text": chunk_text,
                "category": section_category,
            })

        return chunks

    def _split_sentences(self, text_content: str) -> list[str]:
        """Split text into sentences using simple heuristics.

        Splits on period, exclamation, or question mark followed by space
        or end of string, while respecting common abbreviations.
        """
        import re

        # Split on sentence-ending punctuation followed by space or end
        sentences = re.split(r'(?<=[.!?])\s+', text_content)
        return [s for s in sentences if s.strip()]

    async def _get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts via the embedding API.

        Calls the OpenAI-compatible embedding endpoint.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors (each 1536 dimensions).
        """
        if not texts:
            return []

        client = await self._get_client()

        # Process in batches of 20 to avoid API limits
        all_embeddings: list[list[float]] = []
        batch_size = 20

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]

            try:
                response = await client.post(
                    f"{LLM_BASE_URL}/embeddings",
                    json={
                        "model": MODEL_ID,
                        "input": batch,
                    },
                )
                response.raise_for_status()
                data = response.json()

                # OpenAI-compatible response format
                batch_embeddings = [
                    item["embedding"] for item in data["data"]
                ]
                all_embeddings.extend(batch_embeddings)

            except Exception as e:
                logger.error("Embedding API call failed: %s", str(e))
                raise

        return all_embeddings

    async def _retrieve_relevant_chunks(
        self,
        deck_id: uuid.UUID,
        query_text: str,
        db: AsyncSession,
    ) -> list[dict]:
        """Retrieve top-k relevant chunks using cosine similarity search.

        Args:
            deck_id: The deck to search within.
            query_text: The user's question to find relevant content for.
            db: Database session.

        Returns:
            List of dicts with 'text', 'category', and 'similarity' keys.
        """
        # Generate embedding for the query
        query_embeddings = await self._get_embeddings([query_text])
        if not query_embeddings:
            return []

        query_embedding = query_embeddings[0]
        embedding_str = f"[{','.join(str(v) for v in query_embedding)}]"

        # Cosine similarity search using pgvector
        result = await db.execute(
            text(
                "SELECT chunk_text, section_category, "
                "1 - (embedding <=> :query_embedding::vector) AS similarity "
                "FROM deck_embeddings "
                "WHERE deck_id = :deck_id "
                "ORDER BY embedding <=> :query_embedding::vector "
                "LIMIT :top_k"
            ),
            {
                "deck_id": str(deck_id),
                "query_embedding": embedding_str,
                "top_k": TOP_K_CHUNKS,
            },
        )

        rows = result.fetchall()

        # Filter by relevance threshold
        chunks = []
        for row in rows:
            similarity = float(row[2]) if row[2] is not None else 0.0
            if similarity >= RELEVANCE_THRESHOLD:
                chunks.append({
                    "text": row[0],
                    "category": row[1],
                    "similarity": similarity,
                })

        return chunks

    async def _get_scorecard_data(
        self, deck_id: uuid.UUID, db: AsyncSession
    ) -> str:
        """Retrieve scorecard data for the deck formatted as context string.

        Args:
            deck_id: The deck identifier.
            db: Database session.

        Returns:
            Formatted string with scoring results, or empty string if none.
        """
        result = await db.execute(
            select(Scorecard).where(Scorecard.deck_id == deck_id)
        )
        scorecard = result.scalars().first()

        if not scorecard:
            return "No scoring data available for this deck."

        parts = [f"Overall Score: {scorecard.overall_score}/10"]

        if scorecard.market_score is not None:
            parts.append(f"Market Score: {scorecard.market_score}/10")
            if scorecard.market_reasoning:
                parts.append(f"  Reasoning: {scorecard.market_reasoning}")

        if scorecard.team_score is not None:
            parts.append(f"Team Score: {scorecard.team_score}/10")
            if scorecard.team_reasoning:
                parts.append(f"  Reasoning: {scorecard.team_reasoning}")

        if scorecard.business_model_score is not None:
            parts.append(
                f"Business Model Score: {scorecard.business_model_score}/10"
            )
            if scorecard.business_model_reasoning:
                parts.append(
                    f"  Reasoning: {scorecard.business_model_reasoning}"
                )

        if scorecard.competition_score is not None:
            parts.append(f"Competition Score: {scorecard.competition_score}/10")
            if scorecard.competition_reasoning:
                parts.append(
                    f"  Reasoning: {scorecard.competition_reasoning}"
                )

        if scorecard.verdict_summary:
            parts.append(f"Verdict: {scorecard.verdict_summary}")

        if scorecard.failed_categories:
            parts.append(
                f"Failed Categories: {', '.join(scorecard.failed_categories) if isinstance(scorecard.failed_categories, list) else str(scorecard.failed_categories)}"
            )

        return "\n".join(parts)

    async def _get_or_create_session(
        self,
        deck_id: uuid.UUID,
        user_id: uuid.UUID,
        db: AsyncSession,
    ) -> ChatSession:
        """Get existing chat session or create a new one.

        Args:
            deck_id: The deck identifier.
            user_id: The user identifier.
            db: Database session.

        Returns:
            The ChatSession instance.
        """
        result = await db.execute(
            select(ChatSession).where(
                ChatSession.deck_id == deck_id,
                ChatSession.user_id == user_id,
            )
        )
        session = result.scalars().first()

        if session is None:
            session = ChatSession(
                id=uuid.uuid4(),
                deck_id=deck_id,
                user_id=user_id,
                created_at=datetime.utcnow(),
            )
            db.add(session)
            await db.flush()

        return session

    async def _get_session_context(
        self,
        session: ChatSession,
        db: AsyncSession,
        max_messages: int = MAX_SESSION_MESSAGES,
    ) -> str:
        """Retrieve recent conversation history from the session.

        Maintains up to max_messages (20) for coherent multi-turn dialogue.
        Evicts oldest messages when exceeding the cap.

        Args:
            session: The chat session.
            db: Database session.
            max_messages: Maximum number of messages to retain.

        Returns:
            Formatted conversation history string.

        Requirement: 11.4
        """
        result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session.id)
            .order_by(ChatMessage.created_at.desc())
            .limit(max_messages)
        )
        messages = list(reversed(result.scalars().all()))

        if not messages:
            return "No previous conversation."

        history_parts = []
        for msg in messages:
            role_label = "User" if msg.role == "user" else "Assistant"
            history_parts.append(f"{role_label}: {msg.content}")

        return "\n".join(history_parts)

    def _build_prompt(
        self,
        question: str,
        context_chunks: list[dict],
        scorecard_data: str,
        conversation_history: str,
    ) -> str:
        """Construct the system prompt with context for the LLM.

        Args:
            question: The user's current question.
            context_chunks: Retrieved relevant deck chunks.
            scorecard_data: Formatted scorecard information.
            conversation_history: Recent conversation messages.

        Returns:
            The fully constructed system prompt.
        """
        # Format context chunks
        if context_chunks:
            context_parts = []
            for chunk in context_chunks:
                context_parts.append(
                    f"[Section: {chunk['category']}]\n{chunk['text']}"
                )
            context = "\n\n".join(context_parts)
        else:
            context = "No relevant deck content found for this question."

        return SYSTEM_PROMPT.format(
            context=context,
            scoring_data=scorecard_data,
            conversation_history=conversation_history,
        )

    async def _call_llm(self, system_prompt: str, user_message: str) -> str:
        """Call the LLM chat completion endpoint.

        Args:
            system_prompt: The system prompt with context.
            user_message: The user's question.

        Returns:
            The LLM's response text.

        Requirement: 11.5, 11.6
        """
        client = await self._get_client()

        try:
            response = await client.post(
                f"{LLM_BASE_URL}/chat/completions",
                json={
                    "model": MODEL_ID,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 1024,
                },
            )
            response.raise_for_status()
            data = response.json()

            # OpenAI-compatible response format
            return data["choices"][0]["message"]["content"]

        except httpx.HTTPStatusError as e:
            logger.error("LLM API HTTP error: %s", e.response.status_code)
            raise
        except Exception as e:
            logger.error("LLM API call failed: %s", str(e))
            raise

    def _extract_citations(
        self, response_text: str, context_chunks: list[dict]
    ) -> list[str]:
        """Extract cited sections from the LLM response.

        Looks for [Section: category] patterns in the response and matches
        them against the provided context chunks.

        Args:
            response_text: The LLM's response.
            context_chunks: The context chunks that were provided.

        Returns:
            List of unique cited section categories.
        """
        import re

        cited = set()

        # Extract [Section: ...] citations from response
        pattern = r'\[Section:\s*([^\]]+)\]'
        matches = re.findall(pattern, response_text)
        for match in matches:
            cited.add(match.strip())

        # Also include categories from context chunks that appear referenced
        available_categories = {
            chunk["category"] for chunk in context_chunks if chunk.get("category")
        }

        # If LLM didn't use citation format but content is from specific sections
        if not cited and context_chunks:
            # Add categories of the most relevant chunks as implicit citations
            for chunk in context_chunks[:3]:
                if chunk.get("category"):
                    cited.add(chunk["category"])

        # Filter to only categories that exist in context
        valid_cited = [c for c in cited if c in available_categories or c in {
            "market", "team", "business_model", "competition", "uncategorized"
        }]

        return sorted(set(valid_cited))


# Module-level singleton instance
rag_engine = RAGEngine()
