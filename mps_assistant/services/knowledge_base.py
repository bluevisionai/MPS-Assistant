from __future__ import annotations

import json
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence

import numpy as np

from ..config import Settings
from ..database import Database
from ..schemas import ChatResponse, ConversationMessage, ExtractedDocument, RetrievedChunk, SourceCitation
from .chunking import chunk_document
from .application_metadata import build_walkthrough_documents
from .browser_renderer import BrowserRenderer
from .crawler import SiteCrawler
from .extractors import extract_file_document
from .llm import OpenAIService, cited_numbers, parse_structured_answer


class KnowledgeBaseService:
    def __init__(self, settings: Settings, database: Database) -> None:
        self.settings = settings
        self.database = database
        self.llm = OpenAIService(settings)
        self.lock = threading.Lock()
        self.refresh_in_progress = False
        self.last_refresh_started_at: Optional[str] = None
        self.last_refresh_completed_at: Optional[str] = None
        self.last_refresh_error: Optional[str] = None
        self._index_version: Optional[str] = None
        self._embedding_matrix: Optional[np.ndarray] = None
        self._embedding_chunks: List[RetrievedChunk] = []

    def initialize(self) -> None:
        self.database.init()

    def has_content(self) -> bool:
        return self.database.stats()["source_count"] > 0

    def status(self) -> dict:
        stats = self.database.stats()
        return {
            "refresh_in_progress": self.refresh_in_progress,
            "last_refresh_started_at": self.last_refresh_started_at or self.database.get_meta("last_refresh_started_at"),
            "last_refresh_completed_at": self.last_refresh_completed_at or self.database.get_meta("last_refresh_completed_at"),
            "last_refresh_error": self.last_refresh_error or self.database.get_meta("last_refresh_error"),
            "source_count": stats["source_count"],
            "chunk_count": stats["chunk_count"],
        }

    def start_refresh_background(self) -> bool:
        with self.lock:
            if self.refresh_in_progress:
                return False
            self.refresh_in_progress = True
            self.last_refresh_started_at = _utc_now()
            self.last_refresh_error = None
            self.database.set_meta("last_refresh_started_at", self.last_refresh_started_at)
            self.database.set_meta("last_refresh_error", "")
        thread = threading.Thread(target=self._refresh_site_thread, daemon=True)
        thread.start()
        return True

    def refresh_site_now(self) -> None:
        self._refresh_site_thread()

    def harvest_application_walkthrough(self, url: str) -> List[str]:
        downloaded_at = _utc_now()
        with BrowserRenderer(self.settings) as renderer:
            walkthrough = renderer.walk_membership_application(url)

        if walkthrough is None:
            return []

        source_keys = []
        for document in build_walkthrough_documents(walkthrough, downloaded_at):
            self._store_document(document)
            source_keys.append(document.source_key)
        return source_keys

    def ingest_upload(self, upload_path: Path, original_name: str) -> str:
        stored_name = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{original_name}"
        target_path = self.settings.upload_dir / stored_name
        shutil.copyfile(upload_path, target_path)

        document = extract_file_document(
            source_key=f"upload://{stored_name}",
            origin="upload",
            path=target_path,
            downloaded_at=_utc_now(),
            url=None,
            content_type=None,
        )
        self._store_document(document)
        return document.source_key

    def answer_question(self, question: str, messages: Sequence[ConversationMessage] = ()) -> ChatResponse:
        question = question.strip()
        if not question:
            raise ValueError("Question cannot be empty.")

        conversation_history = _normalize_conversation_history(messages, question)
        retrieval_query = self._build_retrieval_query(question, conversation_history)
        retrieved = self.retrieve(retrieval_query, self.settings.retrieval_top_k)
        refusal = "I don't have enough MPS-provided information to answer that confidently."

        if not retrieved:
            return ChatResponse(
                direct_answer=refusal,
                sources=[],
                plain_english="I could not find matching content in the MPS knowledge base.",
                practical_next_steps="Try rephrasing the question or refresh the official MPS site content.",
                limitations="The current knowledge base does not contain supporting MPS passages for this question.",
                refused=True,
            )

        if not self.llm.enabled:
            return ChatResponse(
                direct_answer=refusal,
                sources=self._build_citations(retrieved, list(range(1, min(len(retrieved), 3) + 1))),
                plain_english="The knowledge base found relevant MPS content, but answer generation is disabled because OPENAI_API_KEY is not configured.",
                practical_next_steps="Set OPENAI_API_KEY, then ask the question again.",
                limitations="Without the language model, the app can search and cite sources but cannot assemble the final answer format.",
                refused=True,
            )

        raw_answer = self.llm.answer_question(question, retrieved, conversation_history)
        parsed = parse_structured_answer(raw_answer)
        numbers = cited_numbers(raw_answer, len(retrieved))
        if not numbers:
            numbers = list(range(1, min(len(retrieved), 3) + 1))

        direct_answer = parsed["direct_answer"].strip() or refusal
        refused = _looks_like_refusal(direct_answer, refusal)
        if refused:
            direct_answer = refusal

        direct_answer = _humanize_section_text(direct_answer)
        plain_english = _humanize_section_text(parsed["plain_english"].strip())
        practical_next_steps = _humanize_section_text(parsed["practical_next_steps"].strip())
        limitations = _humanize_section_text(parsed["limitations"].strip())
        direct_answer = _collapse_short_bullets(direct_answer, max_items=3)
        plain_english = _collapse_short_bullets(plain_english, max_items=3)
        limitations = _collapse_short_bullets(limitations, max_items=2)
        plain_english = _drop_redundant_section(plain_english, direct_answer)
        limitations = _drop_redundant_section(limitations, plain_english or direct_answer)
        practical_next_steps = _soften_short_steps(practical_next_steps)

        return ChatResponse(
            direct_answer=direct_answer,
            sources=self._build_citations(retrieved, numbers),
            plain_english=plain_english,
            practical_next_steps=practical_next_steps,
            limitations=limitations,
            refused=refused,
        )

    def _build_retrieval_query(self, question: str, messages: Sequence[ConversationMessage]) -> str:
        if not messages or not _is_follow_up_question(question):
            return question

        prior_context = []
        for message in reversed(messages):
            content = " ".join(message.content.split())
            if not content:
                continue
            prior_context.append(f"{message.role}: {content[:260]}")
            if len(prior_context) >= 3:
                break

        prior_context.reverse()
        if not prior_context:
            return question

        return f"{' '.join(prior_context)} Current question: {question}"

    def retrieve(self, question: str, limit: int) -> List[RetrievedChunk]:
        lexical_ids = self.database.lexical_search(question, self.settings.lexical_top_k)
        semantic_results = self._semantic_search(question, self.settings.semantic_top_k)

        rrf_k = 60
        combined = {}

        for rank, chunk_id in enumerate(lexical_ids, start=1):
            combined.setdefault(chunk_id, {"score": 0.0, "lexical_rank": None, "semantic_rank": None, "semantic_score": None})
            combined[chunk_id]["score"] += 1.0 / (rrf_k + rank)
            combined[chunk_id]["lexical_rank"] = rank

        for rank, (chunk_id, similarity) in enumerate(semantic_results, start=1):
            combined.setdefault(chunk_id, {"score": 0.0, "lexical_rank": None, "semantic_rank": None, "semantic_score": None})
            combined[chunk_id]["score"] += 1.0 / (rrf_k + rank)
            combined[chunk_id]["semantic_rank"] = rank
            combined[chunk_id]["semantic_score"] = similarity

        candidate_ids = list(combined.keys())
        chunks = self.database.fetch_retrieved_chunks(candidate_ids)
        by_id = {chunk.chunk_id: chunk for chunk in chunks}

        ordered_chunks: List[RetrievedChunk] = []
        for chunk_id, metadata in combined.items():
            chunk = by_id.get(chunk_id)
            if chunk is None:
                continue
            chunk.combined_score = float(metadata["score"]) + self._retrieval_boost(question, chunk)
            chunk.lexical_rank = metadata["lexical_rank"]
            chunk.semantic_rank = metadata["semantic_rank"]
            chunk.semantic_score = metadata["semantic_score"]
            ordered_chunks.append(chunk)

        ordered_chunks.sort(
            key=lambda chunk: (
                chunk.combined_score,
                chunk.semantic_score if chunk.semantic_score is not None else -1.0,
            ),
            reverse=True,
        )
        return ordered_chunks[:limit]

    def _refresh_site_thread(self) -> None:
        try:
            crawler = SiteCrawler(self.settings)
            results = crawler.crawl()
            seen_source_keys = []
            for document in results["website_documents"]:
                self._store_document(document)
                seen_source_keys.append(document.source_key)
            self.database.mark_missing_website_sources_stale(seen_source_keys)
            self.last_refresh_completed_at = _utc_now()
            self.last_refresh_error = None
            self.database.set_meta("last_refresh_completed_at", self.last_refresh_completed_at)
            self.database.set_meta("last_refresh_error", "")
        except Exception as error:  # pragma: no cover - surfaced in UI
            self.last_refresh_error = str(error)
            self.database.set_meta("last_refresh_error", self.last_refresh_error)
        finally:
            self.refresh_in_progress = False

    def _store_document(self, document: ExtractedDocument) -> None:
        chunks = chunk_document(document, self.settings)
        if not chunks:
            return

        if self.llm.enabled:
            embeddings = self.llm.embed_texts([chunk.text for chunk in chunks])
            if embeddings:
                for chunk, embedding in zip(chunks, embeddings):
                    chunk.embedding = embedding

        self.database.replace_source(document, chunks)
        self._index_version = None

    def _semantic_search(self, question: str, limit: int) -> List[tuple]:
        if not self.llm.enabled:
            return []

        self._ensure_embedding_index()
        if self._embedding_matrix is None or self._embedding_matrix.size == 0:
            return []

        question_embedding = self.llm.embed_texts([question])
        if not question_embedding:
            return []

        query_vector = np.array(question_embedding[0], dtype=np.float64)
        norm = np.linalg.norm(query_vector)
        if norm == 0.0:
            return []
        query_vector /= norm
        if not np.isfinite(query_vector).all():
            return []

        similarities = np.sum(self._embedding_matrix * query_vector, axis=1)
        if not np.isfinite(similarities).all():
            return []
        if similarities.size == 0:
            return []

        best_indices = np.argsort(similarities)[::-1][:limit]
        results = []
        for index in best_indices:
            similarity = float(similarities[index])
            chunk = self._embedding_chunks[int(index)]
            results.append((chunk.chunk_id, similarity))
        return results

    def _ensure_embedding_index(self) -> None:
        version = self.database.get_meta("kb_version")
        if version and version == self._index_version:
            return

        rows = self.database.load_active_embeddings()
        if not rows:
            self._embedding_matrix = None
            self._embedding_chunks = []
            self._index_version = version
            return

        vectors = []
        chunks = []
        for row in rows:
            vector = json.loads(row["embedding_json"])
            array = np.array(vector, dtype=np.float64)
            norm = np.linalg.norm(array)
            if norm == 0.0:
                continue
            array /= norm
            if not np.isfinite(array).all():
                continue
            vectors.append(array)
            chunks.append(
                RetrievedChunk(
                    chunk_id=int(row["chunk_id"]),
                    text=str(row["text"]),
                    heading=row["heading"],
                    page_number=row["page_number"],
                    url=row["url"],
                    page_title=row["page_title"],
                    document_title=row["document_title"],
                    file_name=row["file_name"],
                    combined_score=0.0,
                    lexical_rank=None,
                    semantic_rank=None,
                    semantic_score=None,
                )
            )

        self._embedding_matrix = np.vstack(vectors) if vectors else None
        self._embedding_chunks = chunks
        self._index_version = version

    def _build_citations(self, retrieved: Sequence[RetrievedChunk], numbers: Sequence[int]) -> List[SourceCitation]:
        citations: List[SourceCitation] = []
        for number in numbers:
            if number < 1 or number > len(retrieved):
                continue
            chunk = retrieved[number - 1]
            citations.append(
                SourceCitation(
                    number=number,
                    url=chunk.url,
                    page_title=chunk.page_title,
                    document_title=chunk.document_title,
                    file_name=chunk.file_name,
                    section_heading=chunk.heading,
                    page_number=chunk.page_number,
                )
            )
        return citations

    def _retrieval_boost(self, question: str, chunk: RetrievedChunk) -> float:
        terms = _significant_terms(question)
        metadata_text = " ".join(
            filter(
                None,
                [
                    chunk.document_title,
                    chunk.page_title,
                    chunk.heading,
                    chunk.file_name,
                    chunk.url,
                ],
            )
        ).lower()
        body_text = chunk.text.lower()[:1800]

        boost = 0.0
        for term in terms:
            if term in metadata_text:
                boost += 0.015
            elif term in body_text:
                boost += 0.003

        if any(term in terms for term in {"application", "form", "join"}) and (
            "apply.medicalprotection.org" in (chunk.url or "")
            or "application" in metadata_text
            or "form" in metadata_text
        ):
            boost += 0.01

        if "student" in terms and "student" in metadata_text:
            boost += 0.03
        if "intern" in terms and "intern" in metadata_text:
            boost += 0.03
        if "occupational" in terms and "occupational" in metadata_text:
            boost += 0.03
        if "private" in terms and "private" in metadata_text:
            boost += 0.03
        if "state" in terms and "state" in metadata_text:
            boost += 0.03
        if "community" in terms and "community" in metadata_text:
            boost += 0.03
        if "practitioner" in terms and "practitioner" in metadata_text:
            boost += 0.03
        if "organisation" in terms and "organisation" in metadata_text:
            boost += 0.03
        if "page" in terms and chunk.page_number == 1:
            boost += 0.005

        return boost


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _significant_terms(text: str) -> List[str]:
    import re

    stopwords = {
        "a",
        "an",
        "and",
        "are",
        "ask",
        "asks",
        "be",
        "can",
        "details",
        "does",
        "first",
        "for",
        "from",
        "how",
        "i",
        "if",
        "in",
        "information",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "or",
        "page",
        "tell",
        "that",
        "the",
        "to",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
        "you",
        "your",
    }
    terms = []
    for term in re.findall(r"[A-Za-z0-9]{3,}", text.lower()):
        if term not in stopwords and term not in terms:
            terms.append(term)
    return terms


def _normalize_conversation_history(
    messages: Sequence[ConversationMessage],
    current_question: str,
) -> List[ConversationMessage]:
    normalized: List[ConversationMessage] = []
    for message in messages:
        content = " ".join(message.content.split())
        if not content:
            continue
        normalized.append(ConversationMessage(role=message.role, content=content))

    if normalized and normalized[-1].role == "user" and normalized[-1].content.strip() == current_question.strip():
        normalized = normalized[:-1]

    return normalized[-6:]


def _is_follow_up_question(question: str) -> bool:
    normalized = question.strip().lower()
    if len(normalized.split()) <= 8:
        return True

    follow_up_terms = (
        "also",
        "and ",
        "but ",
        "does that",
        "for that",
        "for this",
        "how about",
        "if so",
        "it ",
        "same",
        "that ",
        "this ",
        "those ",
        "what about",
        "what if",
        "which one",
    )
    return any(term in normalized for term in follow_up_terms)


def _looks_like_refusal(answer_text: str, refusal_text: str) -> bool:
    def normalize(value: str) -> str:
        normalized = value.strip().lower()
        normalized = normalized.replace("’", "'").replace("‘", "'")
        normalized = normalized.replace("“", '"').replace("”", '"')
        normalized = " ".join(normalized.split())
        return normalized

    return normalize(answer_text) == normalize(refusal_text)


def _humanize_section_text(text: str) -> str:
    if not text:
        return ""

    cleaned = text.strip()
    replacements = [
        (r"(?i)^the excerpts show that\s+", ""),
        (r"(?i)^the excerpts show\s+", ""),
        (r"(?i)^the excerpts say that\s+", ""),
        (r"(?i)^the excerpts say\s+", ""),
        (r"(?i)^the information provided says that\s+", ""),
        (r"(?i)^the information provided says\s+", ""),
        (r"(?i)^the information provided indicates that\s+", ""),
        (r"(?i)^the provided information says that\s+", ""),
        (r"(?i)^the provided information says\s+", ""),
        (r"(?i)^based on the provided sources,\s*", ""),
        (r"(?i)^based on the excerpts,\s*", ""),
    ]

    for pattern, replacement in replacements:
        cleaned = re.sub(pattern, replacement, cleaned)

    cleaned = re.sub(r"(?<=\w)—(?=\w)", " — ", cleaned)
    cleaned = re.sub(r"(?<=\w)–(?=\w)", " – ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r" \n", "\n", cleaned)
    return cleaned.strip()


def _drop_redundant_section(text: str, anchor_text: str) -> str:
    if not text or not anchor_text:
        return text

    text_terms = set(_significant_terms(text))
    anchor_terms = set(_significant_terms(anchor_text))
    if not text_terms or not anchor_terms:
        return text

    overlap = len(text_terms & anchor_terms) / max(1, len(text_terms))
    if overlap >= 0.82:
        return ""

    return text


def _soften_short_steps(text: str) -> str:
    if not text.startswith("- "):
        return text

    steps = [line[2:].strip() for line in text.splitlines() if line.strip().startswith("- ")]
    if not steps or len(steps) > 2:
        return text

    sentence = " ".join(steps)
    sentence = re.sub(r"\s+", " ", sentence).strip()
    return sentence


def _collapse_short_bullets(text: str, max_items: int) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return text
    if not all(line.startswith("- ") for line in lines):
        return text
    if len(lines) > max_items:
        return text

    parts = []
    for line in lines:
        sentence = line[2:].strip()
        if sentence and sentence[-1] not in ".!?":
            sentence = f"{sentence}."
        parts.append(sentence)
    return " ".join(parts).strip()
