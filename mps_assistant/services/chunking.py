from __future__ import annotations

import re
from typing import Iterable, List

from ..config import Settings
from ..schemas import ChunkRecord, ExtractedDocument, ExtractedSection


def chunk_document(document: ExtractedDocument, settings: Settings) -> List[ChunkRecord]:
    chunks: List[ChunkRecord] = []
    chunk_index = 0

    for section in document.sections:
        for piece in _split_section_text(section, settings.max_chunk_chars, settings.chunk_overlap_chars):
            cleaned = normalize_text(piece)
            if not cleaned:
                continue
            chunks.append(
                ChunkRecord(
                    chunk_index=chunk_index,
                    text=cleaned,
                    heading=section.heading,
                    page_number=section.page_number,
                    token_count=max(1, len(cleaned.split())),
                )
            )
            chunk_index += 1

    return chunks


def normalize_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_section_text(section: ExtractedSection, max_chars: int, overlap_chars: int) -> Iterable[str]:
    text = normalize_text(section.text)
    if not text:
        return []

    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n{2,}", text) if paragraph.strip()]
    if not paragraphs:
        paragraphs = [text]

    chunks: List[str] = []
    current = ""

    for paragraph in paragraphs:
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = _tail(current, overlap_chars)

        if len(paragraph) <= max_chars:
            current = paragraph if not current else f"{current}\n\n{paragraph}"
            continue

        sentence_chunks = _split_long_paragraph(paragraph, max_chars)
        if sentence_chunks:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(sentence_chunks[:-1])
            current = sentence_chunks[-1]

    if current:
        chunks.append(current)

    return chunks


def _split_long_paragraph(text: str, max_chars: int) -> List[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if len(sentences) == 1:
        return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]

    chunks: List[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        candidate = sentence if not current else f"{current} {sentence}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks


def _tail(text: str, overlap_chars: int) -> str:
    if len(text) <= overlap_chars:
        return text
    return text[-overlap_chars:].lstrip()
