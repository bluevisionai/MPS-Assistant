from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from pydantic import BaseModel


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
    combined_score: float
    lexical_rank: Optional[int]
    semantic_rank: Optional[int]
    semantic_score: Optional[float]


class ChatRequest(BaseModel):
    question: str


class SourceCitation(BaseModel):
    number: int
    url: Optional[str]
    page_title: Optional[str]
    document_title: Optional[str]
    file_name: Optional[str]
    section_heading: Optional[str]
    page_number: Optional[int]


class ChatResponse(BaseModel):
    direct_answer: str
    sources: List[SourceCitation]
    plain_english: str
    practical_next_steps: str
    limitations: str
    refused: bool


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
