from __future__ import annotations

import json
import sqlite3
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
                """
            )

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
