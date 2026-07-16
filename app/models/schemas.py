"""Pydantic models for PitchLens API request/response schemas."""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime
from uuid import UUID
from enum import Enum


# --- Auth ---


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int  # seconds


# --- Deck ---


class DeckUploadResponse(BaseModel):
    deck_id: UUID
    analysis_id: UUID
    file_name: str
    page_count: int


# --- Extraction ---


class ExtractedSection(BaseModel):
    category: str  # market, team, business_model, competition, uncategorized
    content: str
    page_numbers: List[int]


class ExtractedContent(BaseModel):
    deck_id: UUID
    sections: List[ExtractedSection]
    warnings: List[str] = []
    total_pages: int
    pages_processed: int


# --- Scoring ---


class CategoryScore(BaseModel):
    category: str
    score: int = Field(ge=1, le=10)
    reasoning: str = Field(min_length=50, max_length=500)
    suggestions: List[str] = Field(min_length=1, max_length=3)


# --- Scorecard ---


class Scorecard(BaseModel):
    id: UUID
    analysis_id: UUID
    deck_id: UUID
    overall_score: int = Field(ge=1, le=10)
    category_scores: List[CategoryScore]
    verdict_summary: str = Field(min_length=100, max_length=500)
    category_ranking: List[str]
    failed_categories: List[str] = []
    created_at: datetime


# --- Chat ---


class ChatRequest(BaseModel):
    message: str = Field(max_length=1000)


class ChatResponse(BaseModel):
    response: str
    cited_sections: List[str] = []


# --- History ---


class EvaluationListItem(BaseModel):
    id: UUID
    deck_name: str
    overall_score: int
    created_at: datetime


class PaginatedEvaluations(BaseModel):
    items: List[EvaluationListItem]
    total: int
    page: int
    page_size: int


# --- WebSocket Events ---


class PipelineStage(str, Enum):
    EXTRACTING = "extracting"
    SCORING_MARKET = "scoring_market"
    SCORING_TEAM = "scoring_team"
    SCORING_BUSINESS_MODEL = "scoring_business_model"
    SCORING_COMPETITION = "scoring_competition"
    AGGREGATING = "aggregating"
    COMPLETE = "complete"
    FAILED = "failed"


class WSEvent(BaseModel):
    event_type: str  # stage_change, heartbeat, partial_result, complete, error
    stage: Optional[PipelineStage] = None
    data: Optional[dict] = None
    timestamp: datetime
