"""SQLAlchemy ORM models for PitchLens database schema."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class User(Base):
    """User account model."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    # Relationships
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    decks: Mapped[list["Deck"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    analyses: Mapped[list["Analysis"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    scorecards: Mapped[list["Scorecard"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    chat_sessions: Mapped[list["ChatSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(Base):
    """Refresh token model for JWT auth."""

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


class Deck(Base):
    """Uploaded pitch deck model."""

    __tablename__ = "decks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="decks")
    analyses: Mapped[list["Analysis"]] = relationship(
        back_populates="deck", cascade="all, delete-orphan"
    )
    scorecards: Mapped[list["Scorecard"]] = relationship(
        back_populates="deck", cascade="all, delete-orphan"
    )
    chat_sessions: Mapped[list["ChatSession"]] = relationship(
        back_populates="deck", cascade="all, delete-orphan"
    )
    embeddings: Mapped[list["DeckEmbedding"]] = relationship(
        back_populates="deck", cascade="all, delete-orphan"
    )


class Analysis(Base):
    """Pipeline analysis run model."""

    __tablename__ = "analyses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    deck_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("decks.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    deck: Mapped["Deck"] = relationship(back_populates="analyses")
    user: Mapped["User"] = relationship(back_populates="analyses")
    scorecard: Mapped["Scorecard | None"] = relationship(
        back_populates="analysis", cascade="all, delete-orphan", uselist=False
    )


class Scorecard(Base):
    """Scorecard result from analysis pipeline."""

    __tablename__ = "scorecards"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analyses.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    deck_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("decks.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    overall_score: Mapped[int] = mapped_column(Integer, nullable=False)
    market_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    market_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    market_suggestions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    team_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    team_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    team_suggestions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    business_model_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    business_model_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_model_suggestions: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )
    competition_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    competition_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    competition_suggestions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    verdict_summary: Mapped[str] = mapped_column(Text, nullable=False)
    category_ranking: Mapped[dict] = mapped_column(JSONB, nullable=False)
    failed_categories: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    scorecard_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "overall_score BETWEEN 1 AND 10", name="ck_scorecards_overall_score"
        ),
        CheckConstraint(
            "market_score IS NULL OR market_score BETWEEN 1 AND 10",
            name="ck_scorecards_market_score",
        ),
        CheckConstraint(
            "team_score IS NULL OR team_score BETWEEN 1 AND 10",
            name="ck_scorecards_team_score",
        ),
        CheckConstraint(
            "business_model_score IS NULL OR business_model_score BETWEEN 1 AND 10",
            name="ck_scorecards_business_model_score",
        ),
        CheckConstraint(
            "competition_score IS NULL OR competition_score BETWEEN 1 AND 10",
            name="ck_scorecards_competition_score",
        ),
    )

    # Relationships
    analysis: Mapped["Analysis"] = relationship(back_populates="scorecard")
    deck: Mapped["Deck"] = relationship(back_populates="scorecards")
    user: Mapped["User"] = relationship(back_populates="scorecards")


class ChatSession(Base):
    """Chat session for RAG follow-up questions."""

    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    deck_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("decks.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    # Relationships
    deck: Mapped["Deck"] = relationship(back_populates="chat_sessions")
    user: Mapped["User"] = relationship(back_populates="chat_sessions")
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class ChatMessage(Base):
    """Individual chat message in a session."""

    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    cited_sections: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant')", name="ck_chat_messages_role"
        ),
    )

    # Relationships
    session: Mapped["ChatSession"] = relationship(back_populates="messages")


class DeckEmbedding(Base):
    """Vector embedding for RAG (pgvector)."""

    __tablename__ = "deck_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    deck_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("decks.id", ondelete="CASCADE"), nullable=False
    )
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    section_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Note: The embedding column uses pgvector's vector type.
    # SQLAlchemy doesn't natively support pgvector, so we handle it in migration.
    # For ORM usage, use the pgvector-python package or raw SQL for vector operations.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_deck_embeddings_deck_id", "deck_id"),
    )

    # Relationships
    deck: Mapped["Deck"] = relationship(back_populates="embeddings")


class RateLimitEvent(Base):
    """Rate limit tracking event."""

    __tablename__ = "rate_limit_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    endpoint_category: Mapped[str] = mapped_column(String(50), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        Index(
            "idx_rate_limit_user",
            "user_id",
            "endpoint_category",
            "occurred_at",
        ),
        Index(
            "idx_rate_limit_ip",
            "ip_address",
            "endpoint_category",
            "occurred_at",
        ),
    )
