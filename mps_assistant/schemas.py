from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


@dataclass
class ExtractedSection:
    heading: Optional[str]
    text: str
    page_number: Optional[int] = None


@dataclass
class ExtractedDocument:
    source_key: str
    origin: str
    source_format: str
    url: Optional[str]
    local_path: Optional[str]
    page_title: Optional[str]
    document_title: Optional[str]
    file_name: Optional[str]
    content_type: Optional[str]
    downloaded_at: str
    checksum: str
    sections: List[ExtractedSection] = field(default_factory=list)


@dataclass
class ChunkRecord:
    chunk_index: int
    text: str
    heading: Optional[str]
    page_number: Optional[int]
    token_count: int
    embedding: Optional[List[float]] = None


@dataclass
class RetrievedChunk:
    chunk_id: int
    text: str
    heading: Optional[str]
    page_number: Optional[int]
    url: Optional[str]
    page_title: Optional[str]
    document_title: Optional[str]
    file_name: Optional[str]
    origin: Optional[str]
    source_key: Optional[str]
    local_path: Optional[str]
    combined_score: float
    lexical_rank: Optional[int]
    semantic_rank: Optional[int]
    semantic_score: Optional[float]


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    question: str
    messages: List[ConversationMessage] = Field(default_factory=list)
    session_id: Optional[str] = Field(default=None, description="Session ID for tracking conversation context")


class SourceCitation(BaseModel):
    number: int
    url: Optional[str]
    page_title: Optional[str]
    document_title: Optional[str]
    file_name: Optional[str]
    section_heading: Optional[str]
    page_number: Optional[int]


class RelatedResource(BaseModel):
    kind: Literal["pdf", "form", "chart", "link"]
    title: str
    url: str
    description: Optional[str] = None


class MembershipRecommendation(BaseModel):
    category: str
    title: str
    reason: str
    fit_score: float = 0.0
    next_question: Optional[str] = None


class ChatResponse(BaseModel):
    direct_answer: str
    sources: List[SourceCitation]
    plain_english: str
    practical_next_steps: str
    limitations: str
    refused: bool
    follow_up_suggestions: List[str] = Field(default_factory=list)
    confidence_score: float = 0.0
    confidence_level: Literal["high", "medium", "low", "very_low"] = "low"
    should_escalate: bool = False
    escalation_message: Optional[str] = None
    related_resources: List[RelatedResource] = Field(default_factory=list)
    membership_recommendation: Optional[MembershipRecommendation] = None


class FeedbackRequest(BaseModel):
    session_id: Optional[str] = None
    answer_id: str
    question: str
    answer: str
    helpful: bool
    comment: Optional[str] = None


class FeedbackResponse(BaseModel):
    ok: bool
    message: str


class HandoffRequest(BaseModel):
    session_id: str
    answer_id: Optional[str] = None
    reason: Optional[str] = None
    question: Optional[str] = None
    answer: Optional[str] = None
    confidence_score: Optional[float] = None
    confidence_level: Optional[str] = None
    conversation: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class HandoffResponse(BaseModel):
    ok: bool
    ticket_id: str
    message: str


class AnalyticsKpiItem(BaseModel):
    label: str
    value: str
    delta: Optional[str] = None
    tone: Literal["neutral", "good", "warn"] = "neutral"


class AnalyticsTrendItem(BaseModel):
    label: str
    value: int


class AnalyticsResponse(BaseModel):
    generated_at: str
    refresh_in_progress: bool
    last_refresh_completed_at: Optional[str] = None
    kpis: List[AnalyticsKpiItem] = Field(default_factory=list)
    recent_activity: List[AnalyticsTrendItem] = Field(default_factory=list)
    top_gap_topics: List[GapSummaryItem] = Field(default_factory=list)


class GapSummaryItem(BaseModel):
    topic: str
    count: int
    last_seen_at: str


class GapSummaryResponse(BaseModel):
    total_gap_events: int
    unresolved_gap_events: int
    top_topics: List[GapSummaryItem] = Field(default_factory=list)


class ConversationResumeResponse(BaseModel):
    session_id: str
    turn_count: int
    messages: List[Dict[str, Any]] = Field(default_factory=list)


class UploadResponse(BaseModel):
    ingested_files: int
    source_keys: List[str]


class RefreshResponse(BaseModel):
    started: bool
    message: str


class StatusResponse(BaseModel):
    refresh_in_progress: bool
    last_refresh_started_at: Optional[str]
    last_refresh_completed_at: Optional[str]
    last_refresh_error: Optional[str]
    source_count: int
    chunk_count: int


class OnboardingOtpRequest(BaseModel):
    email: str


class OnboardingOtpVerificationRequest(BaseModel):
    email: str
    code: str


class OnboardingPricingRequest(BaseModel):
    gp_category: str
    gp_hours_band: Optional[str] = None
    gp_intrapartum_basis: Optional[str] = None


class OnboardingSubmissionRequest(BaseModel):
    current_step: int = 7
    membership_category: str
    verified: bool = False
    marketing: Optional[str] = None
    checkboxes: Dict[str, bool] = Field(default_factory=dict)
    fields: Dict[str, Any] = Field(default_factory=dict)
    qualifications: List[Dict[str, Any]] = Field(default_factory=list)
    underwriting_answers: Dict[str, str] = Field(default_factory=dict)
    underwriting_rows: Dict[str, List[Any]] = Field(default_factory=dict)


class OnboardingActionResponse(BaseModel):
    ok: bool
    message: str
    payload: Dict[str, Any] = Field(default_factory=dict)
