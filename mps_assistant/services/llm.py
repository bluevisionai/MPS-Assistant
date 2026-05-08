from __future__ import annotations

import re
from typing import List, Optional, Sequence

from openai import BadRequestError, NotFoundError, OpenAI, PermissionDeniedError

from ..config import Settings
from ..schemas import RetrievedChunk


class OpenAIService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
        self._working_response_model: Optional[str] = None

    @property
    def enabled(self) -> bool:
        return bool(self.settings.openai_api_key)

    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        if not self.enabled or not texts:
            return []
        if self.client is None:
            return []

        embeddings: List[List[float]] = []
        batch_size = 32
        for start in range(0, len(texts), batch_size):
            batch = list(texts[start : start + batch_size])
            response = self.client.embeddings.create(model=self.settings.embedding_model, input=batch)
            embeddings.extend(item.embedding for item in response.data)
        return embeddings

    def answer_question(self, question: str, retrieved_chunks: Sequence[RetrievedChunk]) -> str:
        if not self.enabled:
            raise RuntimeError("OPENAI_API_KEY is required for question answering.")
        if self.client is None:
            raise RuntimeError("OPENAI_API_KEY is required for question answering.")

        context_blocks = []
        for index, chunk in enumerate(retrieved_chunks, start=1):
            location = []
            if chunk.document_title:
                location.append(f"document: {chunk.document_title}")
            if chunk.page_title:
                location.append(f"page title: {chunk.page_title}")
            if chunk.heading:
                location.append(f"section: {chunk.heading}")
            if chunk.page_number:
                location.append(f"page: {chunk.page_number}")
            if chunk.url:
                location.append(f"url: {chunk.url}")

            context_blocks.append(
                f"[{index}] {' | '.join(location)}\n{chunk.text}"
            )

        instructions = (
            "You are MPS Assistant. Answer ONLY from the provided Medical Protection South Africa "
            "source excerpts. Do not use general knowledge. Do not invent policy, pricing, dates, "
            "rules, eligibility, benefits, legal meaning, medical meaning, or indemnity meaning. "
            "If the excerpts do not support a confident answer, the direct answer must be exactly: "
            "\"I don't have enough MPS-provided information to answer that confidently.\" "
            "Never provide legal, medical, financial, or indemnity advice. When wording is ambiguous, "
            "say so and recommend contacting MPS directly. Use citation numbers like [1] or [2] only "
            "for statements supported by the excerpts."
        )
        context_text = "\n\n".join(context_blocks)

        prompt = (
            "Question:\n"
            f"{question}\n\n"
            "Relevant MPS excerpts:\n"
            f"{context_text}\n\n"
            "Return these exact sections and nothing else:\n"
            "DIRECT ANSWER:\n"
            "...\n\n"
            "PLAIN ENGLISH:\n"
            "...\n\n"
            "PRACTICAL NEXT STEPS:\n"
            "...\n\n"
            "UNCERTAINTY:\n"
            "...\n"
        )

        last_error: Optional[Exception] = None
        for model_name in self._response_model_candidates():
            try:
                response = self.client.responses.create(
                    model=model_name,
                    instructions=instructions,
                    input=prompt,
                    max_output_tokens=1200,
                )
            except (BadRequestError, NotFoundError, PermissionDeniedError) as error:
                if not self._is_model_fallback_error(error):
                    raise
                last_error = error
                continue

            self._working_response_model = model_name
            output_text = getattr(response, "output_text", "")
            if output_text:
                return output_text.strip()
            return str(response).strip()

        tried = ", ".join(self._response_model_candidates())
        raise RuntimeError(f"No configured OpenAI response model was available. Tried: {tried}") from last_error

    def _response_model_candidates(self) -> List[str]:
        candidates: List[str] = []
        raw_candidates = [
            self._working_response_model,
            self.settings.openai_model,
            *[item.strip() for item in self.settings.openai_fallback_models.split(",")],
        ]
        for item in raw_candidates:
            if not item:
                continue
            if item in candidates:
                continue
            candidates.append(item)
        return candidates

    def _is_model_fallback_error(self, error: Exception) -> bool:
        if isinstance(error, (NotFoundError, PermissionDeniedError)):
            return True
        if not isinstance(error, BadRequestError):
            return False

        message = str(error).lower()
        model_terms = ("model", "does not exist", "not found", "not available", "unsupported", "access")
        return "model" in message and any(term in message for term in model_terms[1:])


def parse_structured_answer(answer_text: str) -> dict:
    sections = {
        "DIRECT ANSWER": "",
        "PLAIN ENGLISH": "",
        "PRACTICAL NEXT STEPS": "",
        "UNCERTAINTY": "",
    }
    pattern = re.compile(
        r"(DIRECT ANSWER|PLAIN ENGLISH|PRACTICAL NEXT STEPS|UNCERTAINTY):\s*",
        re.IGNORECASE,
    )
    matches = list(pattern.finditer(answer_text))
    if not matches:
        return {
            "direct_answer": answer_text.strip(),
            "plain_english": "",
            "practical_next_steps": "",
            "limitations": "",
        }

    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(answer_text)
        label = match.group(1).upper()
        sections[label] = answer_text[start:end].strip()

    return {
        "direct_answer": sections["DIRECT ANSWER"],
        "plain_english": sections["PLAIN ENGLISH"],
        "practical_next_steps": sections["PRACTICAL NEXT STEPS"],
        "limitations": sections["UNCERTAINTY"],
    }


def cited_numbers(answer_text: str, max_number: int) -> List[int]:
    numbers = []
    seen = set()
    for match in re.findall(r"\[(\d+)\]", answer_text):
        number = int(match)
        if 1 <= number <= max_number and number not in seen:
            seen.add(number)
            numbers.append(number)
    return numbers
