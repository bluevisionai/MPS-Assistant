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
from .question_rewriter import rewrite_question, should_rewrite
from .semantic_intent import SemanticIntentAnalyzer, EnrichedResponseFormulator


class KnowledgeBaseService:
    REFRESH_LOCK_KEY = "refresh_lock_expires_at"
    MANUAL_SOURCE_PREFIX = "manual://"
    MANUAL_SOURCE_ORIGIN = "manual_priority"
    NOISE_SOURCE_PREFIXES = (
        "https://geolocation.onetrust.com/",
        "https://cdn-ukwest.onetrust.com/",
        "https://mps-privacy.my.onetrust.com/",
    )
    DISALLOWED_REGION_MARKERS = (
        "hong kong",
        "hong kong hospital authority",
        "greater bay area",
        "mchk",
        "malaysia",
        "new zealand",
        "singapore",
        "ireland",
        "caribbean",
        "bermuda",
    )

    def __init__(self, settings: Settings, database: Database) -> None:
        self.settings = settings
        self.database = database
        self.llm = OpenAIService(settings)
        self.intent_analyzer = SemanticIntentAnalyzer(self.llm)
        self.response_formulator = EnrichedResponseFormulator(self.llm)
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
        self._sync_manual_priority_sources()

    def has_content(self) -> bool:
        return self.database.stats()["source_count"] > 0

    def status(self) -> dict:
        stats = self.database.stats()
        distributed_refresh_active = self.database.is_refresh_lock_active(self.REFRESH_LOCK_KEY)
        return {
            "refresh_in_progress": self.refresh_in_progress or distributed_refresh_active,
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
            if not self.database.try_acquire_refresh_lock(self.REFRESH_LOCK_KEY, self.settings.refresh_lock_ttl_seconds):
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

    def answer_question(
        self,
        question: str,
        messages: Sequence[ConversationMessage] = (),
        session_id: Optional[str] = None,
    ) -> ChatResponse:
        question = question.strip()
        if not question:
            raise ValueError("Question cannot be empty.")

        conversation_history = _normalize_conversation_history(messages, question)
        refusal = "I don't have enough MPS-provided information to answer that confidently."

        import sys
        print(f"[DEBUG] Original question: {question}", file=sys.stderr)

        retrieval_query = self._build_retrieval_query(question, conversation_history)
        retrieved = self.retrieve(retrieval_query, self.settings.retrieval_top_k)

        print(f"[DEBUG] Retrieved {len(retrieved)} chunks", file=sys.stderr)
        if retrieved:
            for i, chunk in enumerate(retrieved[:2], 1):
                print(
                    f"[DEBUG]   {i}. {chunk.document_title or chunk.file_name} (score: {chunk.combined_score:.3f})",
                    file=sys.stderr,
                )

        avg_score = sum(c.combined_score for c in retrieved) / len(retrieved) if retrieved else 0.0
        if should_rewrite(question, len(retrieved), avg_score):
            print(
                f"[DEBUG] Retrieval confidence low ({len(retrieved)} chunks, avg score {avg_score:.3f}). Trying rewrites...",
                file=sys.stderr,
            )
            rewrites = rewrite_question(question)

            for rewrite in rewrites[1:]:
                print(f"[DEBUG] Trying rewritten question: {rewrite}", file=sys.stderr)
                rewrite_query = self._build_retrieval_query(rewrite, conversation_history)
                rewrite_retrieved = self.retrieve(rewrite_query, self.settings.retrieval_top_k)
                rewrite_avg_score = (
                    sum(c.combined_score for c in rewrite_retrieved) / len(rewrite_retrieved)
                    if rewrite_retrieved
                    else 0.0
                )

                print(
                    f"[DEBUG]   Got {len(rewrite_retrieved)} chunks (avg score: {rewrite_avg_score:.3f})",
                    file=sys.stderr,
                )

                if len(rewrite_retrieved) > len(retrieved) or (
                    len(rewrite_retrieved) > 0 and rewrite_avg_score > avg_score
                ):
                    retrieved = rewrite_retrieved
                    avg_score = rewrite_avg_score
                    question = rewrite
                    print("[DEBUG] Using rewritten question (better results)", file=sys.stderr)
                    break

        if not retrieved:
            follow_ups = self._build_follow_up_suggestions(question, refusal, True)
            related_resources = self._build_related_resources(question, [])
            recommendation = self._build_membership_recommendation(question, None, [])
            confidence_score, confidence_level, should_escalate, escalation_message = self._compute_confidence(
                question=question,
                retrieved=[],
                refused=True,
                intent_signal=0.3,
                direct_answer=refusal,
            )
            self._maybe_log_gap_event(
                question=question,
                session_id=session_id,
                reason="no_retrieval_results",
                confidence_score=confidence_score,
                confidence_level=confidence_level,
                retrieved_count=0,
            )
            return ChatResponse(
                direct_answer=refusal,
                sources=[],
                plain_english="I could not find matching content in the MPS knowledge base.",
                practical_next_steps="Try rephrasing the question or refresh the official MPS site content.",
                limitations="The current knowledge base does not contain supporting MPS passages for this question.",
                refused=True,
                follow_up_suggestions=follow_ups,
                confidence_score=confidence_score,
                confidence_level=confidence_level,
                should_escalate=should_escalate,
                escalation_message=escalation_message,
                related_resources=related_resources,
                membership_recommendation=recommendation,
            )

        if not self.llm.enabled:
            follow_ups = self._build_follow_up_suggestions(question, refusal, True)
            related_resources = self._build_related_resources(question, retrieved)
            recommendation = self._build_membership_recommendation(question, None, retrieved)
            confidence_score, confidence_level, should_escalate, escalation_message = self._compute_confidence(
                question=question,
                retrieved=retrieved,
                refused=True,
                intent_signal=0.4,
                direct_answer=refusal,
            )
            self._maybe_log_gap_event(
                question=question,
                session_id=session_id,
                reason="llm_unavailable",
                confidence_score=confidence_score,
                confidence_level=confidence_level,
                retrieved_count=len(retrieved),
            )
            return ChatResponse(
                direct_answer=refusal,
                sources=self._build_citations(retrieved, list(range(1, min(len(retrieved), 3) + 1))),
                plain_english="The knowledge base found relevant MPS content, but answer generation is disabled because OPENAI_API_KEY is not configured.",
                practical_next_steps="Set OPENAI_API_KEY, then ask the question again.",
                limitations="Without the language model, the app can search and cite sources but cannot assemble the final answer format.",
                refused=True,
                follow_up_suggestions=follow_ups,
                confidence_score=confidence_score,
                confidence_level=confidence_level,
                should_escalate=should_escalate,
                escalation_message=escalation_message,
                related_resources=related_resources,
                membership_recommendation=recommendation,
            )

        print(f"[SEMANTIC] Analyzing intent for: {question[:60]}...", file=sys.stderr)
        intent_analysis = self.intent_analyzer.analyze_intent(question, conversation_history)
        print(f"[SEMANTIC] Intent: {intent_analysis.get_context_summary()}", file=sys.stderr)

        if intent_analysis.semantic_keywords or intent_analysis.retrieval_hints:
            enriched_query = intent_analysis.build_enriched_query()
            print(f"[SEMANTIC] Enriched query: {enriched_query[:80]}...", file=sys.stderr)
            enriched_retrieved = self.retrieve(enriched_query, self.settings.retrieval_top_k)

            if enriched_retrieved:
                enriched_score = sum(c.combined_score for c in enriched_retrieved) / len(enriched_retrieved)
                original_score = sum(c.combined_score for c in retrieved) / len(retrieved) if retrieved else 0
                print(
                    f"[SEMANTIC] Enriched score: {enriched_score:.3f} vs original: {original_score:.3f}",
                    file=sys.stderr,
                )

                if enriched_score > original_score * 0.8:
                    retrieved = enriched_retrieved
                    print("[SEMANTIC] Using enriched retrieval results", file=sys.stderr)

        enriched_response = self.response_formulator.formulate_response(
            question, intent_analysis, retrieved, conversation_history
        )

        if enriched_response:
            print("[SEMANTIC] Using enriched response formulation", file=sys.stderr)
            raw_answer = enriched_response
        else:
            print("[SEMANTIC] Using standard LLM response", file=sys.stderr)
            raw_answer = self.llm.answer_question(question, retrieved, conversation_history)

        parsed = parse_structured_answer(raw_answer)
        numbers = cited_numbers(raw_answer, len(retrieved))
        if not numbers:
            numbers = list(range(1, min(len(retrieved), 3) + 1))

        direct_answer = parsed["direct_answer"].strip() or refusal
        refused = _looks_like_refusal(direct_answer, refusal)
        if refused:
            direct_answer = refusal

        direct_answer = _humanize_section_text(_strip_inline_citations(direct_answer))
        plain_english = _humanize_section_text(_strip_inline_citations(parsed["plain_english"].strip()))
        practical_next_steps = _humanize_section_text(_strip_inline_citations(parsed["practical_next_steps"].strip()))
        limitations = _humanize_section_text(_strip_inline_citations(parsed["limitations"].strip()))
        direct_answer = _collapse_short_bullets(direct_answer, max_items=3)
        plain_english = _collapse_short_bullets(plain_english, max_items=3)
        limitations = _collapse_short_bullets(limitations, max_items=2)
        plain_english = _drop_redundant_section(plain_english, direct_answer)
        limitations = _drop_redundant_section(limitations, plain_english or direct_answer)
        practical_next_steps = _soften_short_steps(practical_next_steps)
        follow_ups = self._build_follow_up_suggestions(question, direct_answer, refused)
        related_resources = self._build_related_resources(question, retrieved)
        recommendation = self._build_membership_recommendation(question, intent_analysis, retrieved)
        intent_signal = 1.0 if (intent_analysis.semantic_keywords or intent_analysis.retrieval_hints) else 0.7
        confidence_score, confidence_level, should_escalate, escalation_message = self._compute_confidence(
            question=question,
            retrieved=retrieved,
            refused=refused,
            intent_signal=intent_signal,
            direct_answer=direct_answer,
        )
        if should_escalate or confidence_level in {"low", "very_low"}:
            reason = "low_confidence" if not refused else "refused_answer"
            self._maybe_log_gap_event(
                question=question,
                session_id=session_id,
                reason=reason,
                confidence_score=confidence_score,
                confidence_level=confidence_level,
                retrieved_count=len(retrieved),
            )

        return ChatResponse(
            direct_answer=direct_answer,
            sources=self._build_citations(retrieved, numbers),
            plain_english=plain_english,
            practical_next_steps=practical_next_steps,
            limitations=limitations,
            refused=refused,
            follow_up_suggestions=follow_ups,
            confidence_score=confidence_score,
            confidence_level=confidence_level,
            should_escalate=should_escalate,
            escalation_message=escalation_message,
            related_resources=related_resources,
            membership_recommendation=recommendation,
        )

    def _build_membership_recommendation(
        self,
        question: str,
        intent_analysis,
        retrieved: Sequence[RetrievedChunk],
    ) -> Optional[dict]:
        """Infer a likely membership category and explain why."""
        text_parts = [question.lower()]
        if intent_analysis is not None:
            text_parts.append(getattr(intent_analysis, "primary_intent", "") or "")
            text_parts.extend(getattr(intent_analysis, "semantic_keywords", []) or [])

        for chunk in list(retrieved)[:3]:
            text_parts.append((chunk.heading or "").lower())
            text_parts.append((chunk.document_title or "").lower())
            text_parts.append((chunk.text or "")[:350].lower())

        corpus = " ".join(text_parts)

        rules = [
            (
                "student",
                ["student", "intern", "community service"],
                {
                    "category": "Student / Early Career",
                    "title": "MPS Student or Early Career Membership",
                    "reason": "Your question suggests a training or early-career context with lower-cost entry options.",
                    "fit_score": 0.84,
                    "next_question": "What documents are needed for a student or intern membership application?",
                },
            ),
            (
                "state",
                ["state doctor", "public sector", "government hospital", "state"],
                {
                    "category": "State Doctor",
                    "title": "MPS State Doctor Membership",
                    "reason": "Your context appears aligned to public-sector practice, which usually maps to state-focused options.",
                    "fit_score": 0.82,
                    "next_question": "What benefits are specific to state doctor membership?",
                },
            ),
            (
                "specialist",
                ["specialist", "consultant", "registrar", "surgeon"],
                {
                    "category": "Private Specialist",
                    "title": "MPS Specialist Membership",
                    "reason": "Your query indicates specialist-level practice and potentially higher-risk clinical scope.",
                    "fit_score": 0.86,
                    "next_question": "How is specialist membership pricing calculated?",
                },
            ),
            (
                "gp",
                ["gp", "general practitioner", "family practice", "private doctor"],
                {
                    "category": "Private GP",
                    "title": "MPS Private GP Membership",
                    "reason": "The question matches general private practice scenarios often associated with GP membership tracks.",
                    "fit_score": 0.83,
                    "next_question": "Can I compare part-time versus full-time GP membership costs?",
                },
            ),
            (
                "organisation",
                ["organisation", "clinic", "practice group", "hospital group", "company"],
                {
                    "category": "Organisation",
                    "title": "MPS Organisation Membership",
                    "reason": "The wording suggests multi-practitioner or entity-level coverage requirements.",
                    "fit_score": 0.8,
                    "next_question": "What information is required for an organisation application?",
                },
            ),
        ]

        for _, keywords, recommendation in rules:
            if any(keyword in corpus for keyword in keywords):
                return recommendation

        if any(x in corpus for x in ["apply", "join", "membership", "cover", "benefit", "eligib"]):
            return {
                "category": "Practitioner (General)",
                "title": "MPS Practitioner Membership",
                "reason": "Based on your query, a practitioner membership path appears most relevant; we can narrow this with role details.",
                "fit_score": 0.68,
                "next_question": "Which membership category should I choose for my exact role and working pattern?",
            }

        return None

    def _build_related_resources(self, question: str, retrieved: Sequence[RetrievedChunk]) -> List[dict]:
        """Build multimodal related resources (PDFs, forms, charts, links)."""
        resources: List[dict] = []
        q = question.lower()

        seen_urls = set()

        for chunk in retrieved:
            file_name = (chunk.file_name or "").strip()
            doc_title = (chunk.document_title or chunk.page_title or file_name or "MPS document").strip()
            url = (chunk.url or "").strip()

            if file_name.lower().endswith(".pdf") and url and url not in seen_urls:
                resources.append(
                    {
                        "kind": "pdf",
                        "title": doc_title,
                        "url": url,
                        "description": "Reference PDF from MPS knowledge base.",
                    }
                )
                seen_urls.add(url)

            if len(resources) >= 2:
                break

        if any(x in q for x in ["apply", "application", "join", "register", "form"]):
            form_url = self.settings.onboarding_portal_url
            if form_url and form_url not in seen_urls:
                resources.append(
                    {
                        "kind": "form",
                        "title": "MPS membership application form",
                        "url": form_url,
                        "description": "Start or continue your online application.",
                    }
                )
                seen_urls.add(form_url)

        if any(x in q for x in ["cost", "price", "fee", "quote", "compare", "chart"]):
            chart_url = "/api/onboarding/rate-card"
            if chart_url not in seen_urls:
                resources.append(
                    {
                        "kind": "chart",
                        "title": "Membership pricing comparison data",
                        "url": chart_url,
                        "description": "Live rate-card data for category and hours comparisons.",
                    }
                )
                seen_urls.add(chart_url)

        if not resources and retrieved:
            first = retrieved[0]
            fallback_url = (first.url or "").strip()
            if fallback_url and fallback_url not in seen_urls:
                resources.append(
                    {
                        "kind": "link",
                        "title": (first.document_title or first.page_title or "MPS reference page"),
                        "url": fallback_url,
                        "description": "Primary reference related to your question.",
                    }
                )

        return resources[:3]

    def _maybe_log_gap_event(
        self,
        question: str,
        session_id: Optional[str],
        reason: str,
        confidence_score: float,
        confidence_level: str,
        retrieved_count: int,
    ) -> None:
        """Persist potential KB coverage gaps for later analysis."""
        normalized_topic = self._normalize_gap_topic(question)
        self.database.log_kb_gap_event(
            question=question,
            normalized_topic=normalized_topic,
            reason=reason,
            confidence_score=confidence_score,
            confidence_level=confidence_level,
            retrieved_count=retrieved_count,
            session_id=session_id,
        )

    def _normalize_gap_topic(self, question: str) -> str:
        q = question.lower()
        if any(x in q for x in ["benefit", "coverage", "cover", "indemnity"]):
            return "benefits-and-coverage"
        if any(x in q for x in ["cost", "price", "fee", "premium", "payment"]):
            return "pricing-and-payments"
        if any(x in q for x in ["apply", "application", "join", "register"]):
            return "application-process"
        if any(x in q for x in ["eligib", "qualif", "requirements"]):
            return "eligibility"
        if any(x in q for x in ["claim", "complaint", "incident", "legal"]):
            return "claims-and-support"
        if any(x in q for x in ["cancel", "termination", "end membership"]):
            return "cancellation"

        tokens = re.findall(r"[a-z0-9]{4,}", q)
        stop = {
            "what", "which", "when", "where", "about", "does", "with", "from",
            "that", "this", "have", "your", "mps", "south", "africa", "membership",
        }
        keywords = [t for t in tokens if t not in stop][:3]
        return "-".join(keywords) if keywords else "general-coverage-gap"

    def _compute_confidence(
        self,
        question: str,
        retrieved: Sequence[RetrievedChunk],
        refused: bool,
        intent_signal: float,
        direct_answer: str,
    ) -> tuple[float, str, bool, Optional[str]]:
        """Compute confidence score and escalation decision."""
        top_k = max(1, int(self.settings.retrieval_top_k))
        retrieval_count_score = min(1.0, len(retrieved) / top_k)

        avg_combined = sum(chunk.combined_score for chunk in retrieved) / len(retrieved) if retrieved else 0.0
        retrieval_quality_score = min(1.0, max(0.0, avg_combined * 9.0))
        retrieval_score = (retrieval_count_score * 0.55) + (retrieval_quality_score * 0.45)

        answer_len = len((direct_answer or "").strip())
        has_substance = 1.0 if answer_len >= 60 else (0.6 if answer_len >= 25 else 0.35)
        formulation_score = 0.0 if refused else has_substance

        score = (
            max(0.0, min(1.0, intent_signal)) * 0.25
            + retrieval_score * 0.5
            + formulation_score * 0.25
        )
        score = max(0.0, min(1.0, score))

        if score >= 0.75:
            level = "high"
        elif score >= 0.55:
            level = "medium"
        elif score >= 0.4:
            level = "low"
        else:
            level = "very_low"

        should_escalate = refused or score < 0.45
        escalation_message = None
        if should_escalate:
            escalation_message = (
                "I may not have enough high-confidence MPS evidence for this specific question. "
                "Please confirm with MPS support before taking action."
            )

        return round(score, 3), level, should_escalate, escalation_message

    def _build_follow_up_suggestions(self, question: str, answer_text: str, refused: bool) -> List[str]:
        """Build quick follow-up suggestions to guide next questions."""
        q = question.lower()
        a = (answer_text or "").lower()

        if refused:
            if any(term in q for term in ["benefit", "cover", "coverage", "protect", "indemnity"]):
                return [
                    "What benefits does MPS membership include for my role?",
                    "What does MPS say is not included in this cover?",
                ]
            if any(term in q for term in ["cost", "price", "fee", "pay", "premium"]):
                return [
                    "What factors affect my membership price?",
                    "Can I get a quote based on my working hours?",
                ]
            if any(term in q for term in ["apply", "application", "join", "signup", "register"]):
                return [
                    "What documents do I need to apply for membership?",
                    "How do I start the MPS membership application?",
                ]
            if any(term in q for term in ["claim", "complaint", "incident", "legal"]):
                return [
                    "What should I do immediately after receiving a complaint?",
                    "How can I contact MPS for urgent support?",
                ]
            return [
                "What can MPS help me with as a member?",
                "How can I contact MPS for this specific question?",
            ]

        suggestions: List[str] = []

        if any(term in q for term in ["benefit", "cover", "coverage", "protect", "indemnity"]):
            suggestions.extend(
                [
                    "What is not included in this cover?",
                    "How do claims work under this membership?",
                    "Which membership option is best for my role?",
                ]
            )
        elif any(term in q for term in ["cost", "price", "fee", "pay", "premium"]):
            suggestions.extend(
                [
                    "What factors affect my membership price?",
                    "Can I get a quote based on my working hours?",
                    "When and how are payments collected?",
                ]
            )
        elif any(term in q for term in ["apply", "application", "join", "signup", "register"]):
            suggestions.extend(
                [
                    "What documents do I need for the application?",
                    "How long does the application approval take?",
                    "Can I save and continue my application later?",
                ]
            )
        elif any(term in q for term in ["eligib", "qualif", "requirement", "can i"]):
            suggestions.extend(
                [
                    "What membership category should I choose?",
                    "What details are needed to confirm eligibility?",
                    "Can part-time practitioners apply?",
                ]
            )
        elif any(term in q for term in ["claim", "complaint", "incident", "legal"]):
            suggestions.extend(
                [
                    "What should I do immediately after an incident?",
                    "How do I notify MPS about a potential claim?",
                    "What support does MPS provide during investigations?",
                ]
            )
        else:
            suggestions.extend(
                [
                    "What are the next steps I should take now?",
                    "How does this affect my membership application?",
                    "Can you explain this in simpler terms for my situation?",
                ]
            )

        if "application" in a and all("application" not in s.lower() for s in suggestions):
            suggestions.append("What are the full membership application steps?")

        cleaned: List[str] = []
        original = question.strip().lower()
        for suggestion in suggestions:
            s = suggestion.strip()
            if not s:
                continue
            if s.lower() == original:
                continue
            if s not in cleaned:
                cleaned.append(s)
            if len(cleaned) >= 3:
                break

        return cleaned

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
            if self._should_exclude_retrieved_chunk(chunk):
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
            self._sync_manual_priority_sources()
            self.last_refresh_completed_at = _utc_now()
            self.last_refresh_error = None
            self.database.set_meta("last_refresh_completed_at", self.last_refresh_completed_at)
            self.database.set_meta("last_refresh_error", "")
        except Exception as error:  # pragma: no cover - surfaced in UI
            self.last_refresh_error = str(error)
            self.database.set_meta("last_refresh_error", self.last_refresh_error)
        finally:
            self.refresh_in_progress = False
            self.database.release_refresh_lock(self.REFRESH_LOCK_KEY)

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
                    origin=row["origin"],
                    source_key=row["source_key"],
                    local_path=row["local_path"],
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

        if self._is_manual_priority_chunk(chunk):
            if any(term in body_text or term in metadata_text for term in terms):
                boost += 0.18
            else:
                boost += 0.02

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

        if self._is_south_africa_or_namibia_chunk(chunk):
            boost += 0.025
        elif chunk.origin == "application_walkthrough":
            boost += 0.01

        if (chunk.source_key or chunk.url or "").startswith("http://"):
            boost -= 0.01

        return boost

    def _sync_manual_priority_sources(self) -> None:
        manual_dir = self.settings.manual_knowledge_dir
        if not manual_dir.exists() or not manual_dir.is_dir():
            return

        seen_source_keys: List[str] = []
        for path in sorted(manual_dir.rglob("*")):
            if not path.is_file() or path.name.startswith("."):
                continue

            source_key = f"{self.MANUAL_SOURCE_PREFIX}{path.relative_to(manual_dir).as_posix()}"
            try:
                document = extract_file_document(
                    source_key=source_key,
                    origin=self.MANUAL_SOURCE_ORIGIN,
                    path=path,
                    downloaded_at=_file_timestamp(path),
                    url=None,
                    content_type=None,
                )
            except Exception:
                continue

            self._store_document(document)
            seen_source_keys.append(source_key)

        self.database.mark_missing_sources_stale(
            self.MANUAL_SOURCE_ORIGIN,
            seen_source_keys,
            stale_all_if_empty=True,
        )

    def _should_exclude_retrieved_chunk(self, chunk: RetrievedChunk) -> bool:
        source_key = (chunk.source_key or chunk.url or "").lower()
        if any(source_key.startswith(prefix) for prefix in self.NOISE_SOURCE_PREFIXES):
            return True

        body_text = (chunk.text or "").lower()
        metadata_text = " ".join(
            filter(
                None,
                [
                    chunk.document_title,
                    chunk.page_title,
                    chunk.file_name,
                    chunk.source_key,
                ],
            )
        ).lower()

        if any(marker in body_text or marker in metadata_text for marker in self.DISALLOWED_REGION_MARKERS):
            return True

        return False

    def _is_manual_priority_chunk(self, chunk: RetrievedChunk) -> bool:
        return (
            chunk.origin == self.MANUAL_SOURCE_ORIGIN
            or (chunk.source_key or "").startswith(self.MANUAL_SOURCE_PREFIX)
            or "manual_files/" in (chunk.local_path or "").replace("\\", "/")
        )

    def _is_south_africa_or_namibia_chunk(self, chunk: RetrievedChunk) -> bool:
        metadata_text = " ".join(
            filter(
                None,
                [
                    chunk.document_title,
                    chunk.page_title,
                    chunk.file_name,
                    chunk.source_key,
                    chunk.url,
                ],
            )
        ).lower()
        body_text = (chunk.text or "").lower()[:1400]
        relevant_markers = (
            "south africa",
            "south-africa",
            "rsa",
            "namibia",
            "/southafrica",
            "/za/",
            "hpcsa",
            "hpcna",
            "consumer protection act",
        )
        return any(marker in metadata_text or marker in body_text for marker in relevant_markers)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_timestamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


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


def _strip_inline_citations(text: str) -> str:
    if not text:
        return ""

    cleaned = re.sub(r"\s*\[(\d+)\]", "", text)
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r" ?\n", "\n", cleaned)
    return cleaned.strip()


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
