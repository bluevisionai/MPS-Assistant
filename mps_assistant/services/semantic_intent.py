"""
Intent-based semantic retrieval system using AI for multi-stage question processing.

Pipeline:
1. Intent Analysis: Use LLM to understand what user is really asking
2. Semantic Retrieval: Use intent to find more relevant content
3. Response Formulation: Use LLM to craft intelligent answer from retrieved content
"""

from __future__ import annotations

import json
from typing import Optional, Sequence

from ..schemas import ConversationMessage, RetrievedChunk
from .llm import OpenAIService


class SemanticIntentAnalyzer:
    """Analyzes user questions to extract intent and generate enriched retrieval queries."""

    def __init__(self, llm: OpenAIService) -> None:
        self.llm = llm

    def analyze_intent(
        self,
        question: str,
        conversation_history: Sequence[ConversationMessage] = (),
    ) -> IntentAnalysis:
        """
        Analyze user question to extract intent, implied questions, and retrieval hints.
        
        Args:
            question: The user's question
            conversation_history: Previous messages for context
            
        Returns:
            IntentAnalysis with semantic understanding
        """
        if not self.llm.enabled:
            # Fallback: return basic analysis
            return IntentAnalysis(
                primary_intent=question,
                implied_questions=[],
                semantic_keywords=[],
                retrieval_hints=[],
            )

        try:
            response = self.llm.client.chat.completions.create(
                model=self.llm._working_response_model or self.llm.settings.openai_model,
                messages=self._build_intent_messages(question, conversation_history),
                temperature=0.3,
                max_completion_tokens=300,
            )
            
            analysis_text = response.choices[0].message.content.strip()
            return self._parse_intent_response(analysis_text, question)
            
        except Exception as e:
            print(f"[WARN] Intent analysis failed: {e}")
            return IntentAnalysis(
                primary_intent=question,
                implied_questions=[],
                semantic_keywords=[],
                retrieval_hints=[],
            )

    def _build_intent_messages(
        self, 
        question: str, 
        conversation_history: Sequence[ConversationMessage]
    ) -> list:
        """Build messages for intent analysis prompt."""
        history_context = ""
        if conversation_history:
            recent = list(conversation_history)[-3:]  # Last 3 exchanges
            history_context = "Previous conversation:\n"
            for msg in recent:
                history_context += f"{msg.role}: {msg.content[:150]}\n"

        prompt = f"""Analyze this MPS question to extract the user's underlying intent.

{history_context}

Current question: "{question}"

Respond with ONLY valid JSON (no markdown, no code blocks) in this format:
{{
  "primary_intent": "The main thing user wants to know",
  "implied_questions": ["What sub-questions might this imply?", "Other related questions?"],
  "semantic_keywords": ["key", "terms", "to", "search"],
  "retrieval_hints": ["Hint about what type of content to look for"]
}}

Be concise. Extract 2-3 implied questions and 3-4 keywords max."""

        return [
            {
                "role": "system",
                "content": "You are an intent analyzer for Medical Protection South Africa questions. Extract semantic meaning and search hints.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]

    def _parse_intent_response(self, response_text: str, original_question: str) -> IntentAnalysis:
        """Parse LLM response into IntentAnalysis."""
        try:
            # Try to extract JSON from response
            json_text = response_text
            if "```" in json_text:
                json_text = json_text.split("```")[1]
                if json_text.startswith("json"):
                    json_text = json_text[4:]
            
            data = json.loads(json_text)
            
            return IntentAnalysis(
                primary_intent=data.get("primary_intent", original_question),
                implied_questions=data.get("implied_questions", []),
                semantic_keywords=data.get("semantic_keywords", []),
                retrieval_hints=data.get("retrieval_hints", []),
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            # Fallback
            return IntentAnalysis(
                primary_intent=original_question,
                implied_questions=[],
                semantic_keywords=[],
                retrieval_hints=[],
            )


class IntentAnalysis:
    """Result of intent analysis."""

    def __init__(
        self,
        primary_intent: str,
        implied_questions: list,
        semantic_keywords: list,
        retrieval_hints: list,
    ):
        self.primary_intent = primary_intent
        self.implied_questions = implied_questions
        self.semantic_keywords = semantic_keywords
        self.retrieval_hints = retrieval_hints

    def build_enriched_query(self) -> str:
        """
        Build an enriched retrieval query using all available information.
        
        Returns:
            A query optimized for semantic and lexical search
        """
        parts = [self.primary_intent]
        
        if self.semantic_keywords:
            parts.extend(self.semantic_keywords[:3])
        
        if self.implied_questions:
            # Add the most important implied question
            parts.append(self.implied_questions[0])
        
        return " ".join(parts)

    def get_context_summary(self) -> str:
        """Get a summary of the analysis for logging."""
        return f"Intent: {self.primary_intent} | Keywords: {', '.join(self.semantic_keywords)}"


class EnrichedResponseFormulator:
    """Uses retrieved content plus intent to formulate better responses."""

    def __init__(self, llm: OpenAIService) -> None:
        self.llm = llm

    def formulate_response(
        self,
        question: str,
        intent_analysis: IntentAnalysis,
        retrieved_chunks: Sequence[RetrievedChunk],
        conversation_history: Sequence[ConversationMessage] = (),
    ) -> str:
        """
        Formulate an answer that addresses the user's true intent, not just the literal question.
        
        Args:
            question: Original question
            intent_analysis: Analysis of user intent
            retrieved_chunks: Relevant content from KB
            conversation_history: Previous messages
            
        Returns:
            A formulated answer addressing the intent
        """
        if not self.llm.enabled or not retrieved_chunks:
            return None

        # Build context from retrieved chunks
        context_blocks = []
        for idx, chunk in enumerate(retrieved_chunks, 1):
            location = []
            if chunk.document_title:
                location.append(f"document: {chunk.document_title}")
            if chunk.page_title:
                location.append(f"page: {chunk.page_title}")
            if chunk.heading:
                location.append(f"section: {chunk.heading}")
            
            context_blocks.append(f"[{idx}] {' | '.join(location)}\n{chunk.text}")

        context = "\n\n".join(context_blocks)

        # Build prompt that considers intent
        prompt = self._build_formulation_prompt(
            question,
            intent_analysis,
            context,
            conversation_history,
        )

        try:
            response = self.llm.client.chat.completions.create(
                model=self.llm._working_response_model or self.llm.settings.openai_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are Medical Protection's chat assistant for South Africa. Answer based ONLY on provided MPS excerpts. "
                            "Address the user's underlying intent, not just literal question. "
                            "Use citations [1], [2] etc. Be concise and practical. Use first-person plural such as "
                            "\"we\" and \"our\" for member-facing wording instead of referring to Medical Protection in the third person. "
                            "Keep wording factual and constructive, and avoid negative framing about MPS."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.5,
                max_completion_tokens=500,
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            print(f"[WARN] Response formulation failed: {e}")
            return None

    def _build_formulation_prompt(
        self,
        question: str,
        intent: IntentAnalysis,
        context: str,
        history: Sequence[ConversationMessage],
    ) -> str:
        """Build prompt for response formulation."""
        prompt = f"""Answer this question addressing the user's true intent:

Question asked: "{question}"

Underlying intent: "{intent.primary_intent}"

Related questions they might also have:
{chr(10).join(f"- {q}" for q in intent.implied_questions[:2])}

Relevant MPS excerpts:
{context}

Guidelines:
1. Address the primary intent, not just the literal question
2. Reference any related implied questions if relevant
3. Use only the provided excerpts
4. Include citation numbers [1], [2] etc
5. Be direct and practical
6. If content doesn't fully answer intent, state what is known and what still needs confirmation in neutral wording"""

        return prompt


if __name__ == "__main__":
    # Example usage
    print("Intent Analysis System Ready")
    print("\nExample intent extraction:")
    example_questions = [
        "What are the benefits of MPS products?",
        "How do I join?",
        "What happens if I get a complaint?",
    ]
    for q in example_questions:
        print(f"\nQuestion: {q}")
        print(f"  → Implied: More specific about what user needs to know")
