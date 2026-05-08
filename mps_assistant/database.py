from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from .schemas import ChunkRecord, ExtractedDocument, RetrievedChunk


class Database:
    def __init__(self, path: Path, journal_mode: str = "WAL") -> None:
        self.path = path
        self.journal_mode = journal_mode.upper()

    @contextmanager
    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000;")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                f"""
                PRAGMA journal_mode={self.journal_mode};
                PRAGMA foreign_keys=ON;

                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_key TEXT NOT NULL UNIQUE,
                    origin TEXT NOT NULL,
                    source_format TEXT NOT NULL,
                    url TEXT,
                    local_path TEXT,
                    page_title TEXT,
                    document_title TEXT,
                    file_name TEXT,
                    content_type TEXT,
                    downloaded_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active'
                );

                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id INTEGER NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    heading TEXT,
                    page_number INTEGER,
                    text TEXT NOT NULL,
                    token_count INTEGER NOT NULL,
                    embedding_json TEXT,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    chunk_id UNINDEXED,
                    text,
                    heading,
                    page_title,
                    document_title,
                    url,
                    file_name,
                    tokenize='porter unicode61'
                );

                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_sources_origin_status ON sources(origin, status);
                CREATE INDEX IF NOT EXISTS idx_chunks_source_id ON chunks(source_id);
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL UNIQUE,
                    user_role TEXT,
                    user_situation TEXT,
                    context_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    message_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'active'
                );

                CREATE TABLE IF NOT EXISTS conversation_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER NOT NULL,
                    turn_number INTEGER NOT NULL,
                    user_message TEXT NOT NULL,
                    assistant_response TEXT NOT NULL,
                    response_json TEXT,
                    question_topic TEXT,
                    extracted_context_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_conversations_session_id ON conversations(session_id);
                CREATE INDEX IF NOT EXISTS idx_conversation_turns_conversation_id ON conversation_turns(conversation_id);

                CREATE TABLE IF NOT EXISTS answer_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    answer_id TEXT NOT NULL,
                    session_id TEXT,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    helpful INTEGER NOT NULL,
                    comment TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(answer_id, session_id)
                );

                CREATE INDEX IF NOT EXISTS idx_answer_feedback_answer_id ON answer_feedback(answer_id);
                CREATE INDEX IF NOT EXISTS idx_answer_feedback_created_at ON answer_feedback(created_at);

                CREATE TABLE IF NOT EXISTS kb_gap_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    question TEXT NOT NULL,
                    normalized_topic TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    confidence_score REAL,
                    confidence_level TEXT,
                    retrieved_count INTEGER DEFAULT 0,
                    resolved INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_kb_gap_events_created_at ON kb_gap_events(created_at);
                CREATE INDEX IF NOT EXISTS idx_kb_gap_events_topic ON kb_gap_events(normalized_topic);
                CREATE INDEX IF NOT EXISTS idx_kb_gap_events_resolved ON kb_gap_events(resolved);

                CREATE TABLE IF NOT EXISTS handoff_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id TEXT NOT NULL UNIQUE,
                    session_id TEXT NOT NULL,
                    answer_id TEXT,
                    reason TEXT,
                    question TEXT,
                    answer TEXT,
                    confidence_score REAL,
                    confidence_level TEXT,
                    conversation_json TEXT NOT NULL,
                    metadata_json TEXT,
                    status TEXT NOT NULL DEFAULT 'queued',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_handoff_requests_session_id ON handoff_requests(session_id);
                CREATE INDEX IF NOT EXISTS idx_handoff_requests_created_at ON handoff_requests(created_at);
                """
            )

            # Lightweight schema migration for existing databases.
            turn_cols = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(conversation_turns)").fetchall()
            }
            if "response_json" not in turn_cols:
                conn.execute("ALTER TABLE conversation_turns ADD COLUMN response_json TEXT")

    def replace_source(self, document: ExtractedDocument, chunks: Sequence[ChunkRecord]) -> int:
        now = _utc_now()
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM sources WHERE source_key = ?",
                (document.source_key,),
            ).fetchone()

            if existing:
                source_id = int(existing["id"])
                conn.execute("DELETE FROM chunks_fts WHERE chunk_id IN (SELECT id FROM chunks WHERE source_id = ?)", (source_id,))
                conn.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))
                conn.execute(
                    """
                    UPDATE sources
                    SET origin = ?, source_format = ?, url = ?, local_path = ?, page_title = ?,
                        document_title = ?, file_name = ?, content_type = ?, downloaded_at = ?,
                        last_seen_at = ?, checksum = ?, status = 'active'
                    WHERE id = ?
                    """,
                    (
                        document.origin,
                        document.source_format,
                        document.url,
                        document.local_path,
                        document.page_title,
                        document.document_title,
                        document.file_name,
                        document.content_type,
                        document.downloaded_at,
                        document.downloaded_at,
                        document.checksum,
                        source_id,
                    ),
                )
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO sources (
                        source_key, origin, source_format, url, local_path, page_title,
                        document_title, file_name, content_type, downloaded_at, last_seen_at,
                        checksum, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
                    """,
                    (
                        document.source_key,
                        document.origin,
                        document.source_format,
                        document.url,
                        document.local_path,
                        document.page_title,
                        document.document_title,
                        document.file_name,
                        document.content_type,
                        document.downloaded_at,
                        document.downloaded_at,
                        document.checksum,
                    ),
                )
                source_id = int(cursor.lastrowid)

            for chunk in chunks:
                cursor = conn.execute(
                    """
                    INSERT INTO chunks (
                        source_id, chunk_index, heading, page_number, text, token_count,
                        embedding_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        chunk.chunk_index,
                        chunk.heading,
                        chunk.page_number,
                        chunk.text,
                        chunk.token_count,
                        json.dumps(chunk.embedding) if chunk.embedding is not None else None,
                        now,
                    ),
                )
                chunk_id = int(cursor.lastrowid)
                conn.execute(
                    """
                    INSERT INTO chunks_fts (
                        chunk_id, text, heading, page_title, document_title, url, file_name
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk_id,
                        chunk.text,
                        chunk.heading or "",
                        document.page_title or "",
                        document.document_title or "",
                        document.url or "",
                        document.file_name or "",
                    ),
                )

            self.set_meta_with_connection(conn, "kb_version", now)

        return source_id

    def mark_missing_website_sources_stale(self, seen_source_keys: Sequence[str]) -> None:
        if not seen_source_keys:
            return

        placeholders = ",".join("?" for _ in seen_source_keys)
        with self.connect() as conn:
            conn.execute(
                f"""
                UPDATE sources
                SET status = 'stale'
                WHERE origin = 'website' AND source_key NOT IN ({placeholders})
                """,
                tuple(seen_source_keys),
            )
            self.set_meta_with_connection(conn, "kb_version", _utc_now())

    def set_meta(self, key: str, value: str) -> None:
        with self.connect() as conn:
            self.set_meta_with_connection(conn, key, value)

    def set_meta_with_connection(self, conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute(
            """
            INSERT INTO meta(key, value)
            VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )

    def get_meta(self, key: str) -> Optional[str]:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def lexical_search(self, query: str, limit: int) -> List[int]:
        fts_query = _build_fts_query(query)
        if not fts_query:
            return []

        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT chunk_id
                FROM chunks_fts
                WHERE chunks_fts MATCH ?
                ORDER BY bm25(chunks_fts)
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()

        return [int(row["chunk_id"]) for row in rows]

    def fetch_retrieved_chunks(self, chunk_ids: Sequence[int]) -> List[RetrievedChunk]:
        if not chunk_ids:
            return []

        placeholders = ",".join("?" for _ in chunk_ids)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    c.id AS chunk_id,
                    c.text,
                    c.heading,
                    c.page_number,
                    s.url,
                    s.page_title,
                    s.document_title,
                    s.file_name
                FROM chunks c
                JOIN sources s ON s.id = c.source_id
                WHERE c.id IN ({placeholders}) AND s.status = 'active'
                """,
                tuple(chunk_ids),
            ).fetchall()

        by_id: Dict[int, RetrievedChunk] = {}
        for row in rows:
            chunk_id = int(row["chunk_id"])
            by_id[chunk_id] = RetrievedChunk(
                chunk_id=chunk_id,
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

        ordered = [by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in by_id]
        return ordered

    def load_active_embeddings(self) -> List[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.id AS chunk_id,
                    c.embedding_json,
                    c.text,
                    c.heading,
                    c.page_number,
                    s.url,
                    s.page_title,
                    s.document_title,
                    s.file_name
                FROM chunks c
                JOIN sources s ON s.id = c.source_id
                WHERE s.status = 'active' AND c.embedding_json IS NOT NULL
                ORDER BY c.id ASC
                """
            ).fetchall()
        return rows

    def stats(self) -> Dict[str, int]:
        with self.connect() as conn:
            source_count = conn.execute(
                "SELECT COUNT(*) AS count FROM sources WHERE status = 'active'"
            ).fetchone()["count"]
            chunk_count = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM chunks c
                JOIN sources s ON s.id = c.source_id
                WHERE s.status = 'active'
                """
            ).fetchone()["count"]
        return {"source_count": int(source_count), "chunk_count": int(chunk_count)}

    def create_or_get_conversation(self, session_id: str) -> int:
        """Create or retrieve a conversation by session_id."""
        now = _utc_now()
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM conversations WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            
            if existing:
                return int(existing["id"])
            
            cursor = conn.execute(
                """
                INSERT INTO conversations (session_id, created_at, updated_at)
                VALUES (?, ?, ?)
                """,
                (session_id, now, now),
            )
            return int(cursor.lastrowid)
    
    def save_conversation_turn(
        self,
        conversation_id: int,
        turn_number: int,
        user_message: str,
        assistant_response: str,
        response_json: Optional[str] = None,
        question_topic: Optional[str] = None,
        extracted_context_json: Optional[str] = None,
    ) -> int:
        """Save a turn in the conversation."""
        now = _utc_now()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO conversation_turns (
                    conversation_id, turn_number, user_message, assistant_response,
                    response_json, question_topic, extracted_context_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    turn_number,
                    user_message,
                    assistant_response,
                    response_json,
                    question_topic,
                    extracted_context_json,
                    now,
                ),
            )
            
            # Update conversation metadata
            conn.execute(
                """
                UPDATE conversations
                SET message_count = message_count + 1, updated_at = ?
                WHERE id = ?
                """,
                (now, conversation_id),
            )
            
            return int(cursor.lastrowid)
    
    def get_conversation_history(self, conversation_id: int, limit: int = 20) -> List[Dict]:
        """Get recent conversation turns."""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    turn_number, user_message, assistant_response,
                    response_json, question_topic, extracted_context_json, created_at
                FROM conversation_turns
                WHERE conversation_id = ?
                ORDER BY turn_number DESC
                LIMIT ?
                """,
                (conversation_id, limit),
            ).fetchall()
        
        return [dict(row) for row in reversed(rows)]

    def get_conversation_turn_count(self, conversation_id: int) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM conversation_turns WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        return int(row["count"] or 0)
    
    def update_conversation_context(
        self,
        conversation_id: int,
        context_json: str,
        user_role: Optional[str] = None,
        user_situation: Optional[str] = None,
    ) -> None:
        """Update stored context for a conversation."""
        now = _utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE conversations
                SET context_json = ?, user_role = ?, user_situation = ?, updated_at = ?
                WHERE id = ?
                """,
                (context_json, user_role, user_situation, now, conversation_id),
            )
    
    def get_conversation_context(self, conversation_id: int) -> Optional[str]:
        """Get stored context JSON for a conversation."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT context_json FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        
        return None if row is None else row["context_json"]

    def upsert_answer_feedback(
        self,
        answer_id: str,
        session_id: Optional[str],
        question: str,
        answer: str,
        helpful: bool,
        comment: Optional[str] = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO answer_feedback (
                    answer_id, session_id, question, answer, helpful, comment, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(answer_id, session_id) DO UPDATE SET
                    helpful = excluded.helpful,
                    comment = excluded.comment,
                    question = excluded.question,
                    answer = excluded.answer,
                    created_at = excluded.created_at
                """,
                (
                    answer_id,
                    session_id,
                    question,
                    answer,
                    1 if helpful else 0,
                    comment,
                    _utc_now(),
                ),
            )

    def feedback_summary(self) -> Dict[str, int]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN helpful = 1 THEN 1 ELSE 0 END) AS helpful,
                    SUM(CASE WHEN helpful = 0 THEN 1 ELSE 0 END) AS not_helpful
                FROM answer_feedback
                """
            ).fetchone()
        return {
            "total": int(row["total"] or 0),
            "helpful": int(row["helpful"] or 0),
            "not_helpful": int(row["not_helpful"] or 0),
        }

    def log_kb_gap_event(
        self,
        question: str,
        normalized_topic: str,
        reason: str,
        confidence_score: Optional[float],
        confidence_level: Optional[str],
        retrieved_count: int,
        session_id: Optional[str] = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO kb_gap_events (
                    session_id, question, normalized_topic, reason,
                    confidence_score, confidence_level, retrieved_count,
                    resolved, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    session_id,
                    question,
                    normalized_topic,
                    reason,
                    confidence_score,
                    confidence_level,
                    int(retrieved_count),
                    _utc_now(),
                ),
            )

    def kb_gap_summary(self, top_n: int = 10) -> Dict[str, object]:
        with self.connect() as conn:
            totals = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_gap_events,
                    SUM(CASE WHEN resolved = 0 THEN 1 ELSE 0 END) AS unresolved_gap_events
                FROM kb_gap_events
                """
            ).fetchone()

            topics = conn.execute(
                """
                SELECT
                    normalized_topic AS topic,
                    COUNT(*) AS count,
                    MAX(created_at) AS last_seen_at
                FROM kb_gap_events
                WHERE resolved = 0
                GROUP BY normalized_topic
                ORDER BY count DESC, last_seen_at DESC
                LIMIT ?
                """,
                (int(max(1, top_n)),),
            ).fetchall()

        return {
            "total_gap_events": int(totals["total_gap_events"] or 0),
            "unresolved_gap_events": int(totals["unresolved_gap_events"] or 0),
            "top_topics": [
                {
                    "topic": str(row["topic"]),
                    "count": int(row["count"]),
                    "last_seen_at": str(row["last_seen_at"]),
                }
                for row in topics
            ],
        }

    def create_handoff_request(
        self,
        session_id: str,
        conversation: List[Dict[str, object]],
        answer_id: Optional[str] = None,
        reason: Optional[str] = None,
        question: Optional[str] = None,
        answer: Optional[str] = None,
        confidence_score: Optional[float] = None,
        confidence_level: Optional[str] = None,
        metadata: Optional[Dict[str, object]] = None,
    ) -> str:
        ticket_id = f"HOF-{uuid.uuid4().hex[:10].upper()}"
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO handoff_requests (
                    ticket_id, session_id, answer_id, reason, question, answer,
                    confidence_score, confidence_level, conversation_json,
                    metadata_json, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)
                """,
                (
                    ticket_id,
                    session_id,
                    answer_id,
                    reason,
                    question,
                    answer,
                    confidence_score,
                    confidence_level,
                    json.dumps(conversation),
                    json.dumps(metadata or {}),
                    _utc_now(),
                ),
            )
        return ticket_id

    def analytics_summary(self) -> Dict[str, object]:
        with self.connect() as conn:
            source_stats = self.stats()
            conversation_totals = conn.execute(
                """
                SELECT
                    COUNT(*) AS conversation_count,
                    COALESCE(SUM(message_count), 0) AS message_count
                FROM conversations
                """
            ).fetchone()
            feedback_totals = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN helpful = 1 THEN 1 ELSE 0 END) AS helpful,
                    SUM(CASE WHEN helpful = 0 THEN 1 ELSE 0 END) AS not_helpful
                FROM answer_feedback
                """
            ).fetchone()
            handoff_totals = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END) AS queued
                FROM handoff_requests
                """
            ).fetchone()
            recent_activity = conn.execute(
                """
                SELECT 'Questions (24h)' AS label, COUNT(*) AS value
                FROM conversation_turns
                WHERE created_at >= datetime('now', '-1 day')
                UNION ALL
                SELECT 'Feedback (24h)' AS label, COUNT(*) AS value
                FROM answer_feedback
                WHERE created_at >= datetime('now', '-1 day')
                UNION ALL
                SELECT 'Handoffs (24h)' AS label, COUNT(*) AS value
                FROM handoff_requests
                WHERE created_at >= datetime('now', '-1 day')
                UNION ALL
                SELECT 'Gap events (24h)' AS label, COUNT(*) AS value
                FROM kb_gap_events
                WHERE created_at >= datetime('now', '-1 day')
                """
            ).fetchall()

        helpful_total = int(feedback_totals["helpful"] or 0)
        feedback_total = int(feedback_totals["total"] or 0)
        helpful_rate = round((helpful_total / feedback_total) * 100) if feedback_total else 0
        gap_summary = self.kb_gap_summary(top_n=5)

        return {
            "source_count": int(source_stats["source_count"] or 0),
            "chunk_count": int(source_stats["chunk_count"] or 0),
            "conversation_count": int(conversation_totals["conversation_count"] or 0),
            "message_count": int(conversation_totals["message_count"] or 0),
            "feedback_total": feedback_total,
            "helpful_total": helpful_total,
            "not_helpful_total": int(feedback_totals["not_helpful"] or 0),
            "helpful_rate": helpful_rate,
            "handoff_total": int(handoff_totals["total"] or 0),
            "handoff_queued": int(handoff_totals["queued"] or 0),
            "recent_activity": [
                {
                    "label": str(row["label"]),
                    "value": int(row["value"] or 0),
                }
                for row in recent_activity
            ],
            "top_gap_topics": gap_summary["top_topics"],
            "total_gap_events": int(gap_summary["total_gap_events"] or 0),
            "unresolved_gap_events": int(gap_summary["unresolved_gap_events"] or 0),
        }


def _build_fts_query(query: str) -> str:
    import re

    stopwords = {
        "a",
        "an",
        "and",
        "are",
        "be",
        "can",
        "do",
        "does",
        "for",
        "from",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "or",
        "should",
        "that",
        "the",
        "to",
        "what",
        "when",
        "where",
        "who",
        "why",
        "will",
        "with",
        "you",
        "your",
    }

    terms = [
        term
        for term in re.findall(r"[A-Za-z0-9]{3,}", query.lower())
        if term not in stopwords
    ]
    if not terms:
        terms = re.findall(r"[A-Za-z0-9]{2,}", query.lower())
    if not terms:
        return ""
    unique_terms = []
    seen = set()
    for term in terms:
        if term not in seen:
            unique_terms.append(term)
            seen.add(term)
    return " OR ".join(f'"{term}"' for term in unique_terms[:12])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
