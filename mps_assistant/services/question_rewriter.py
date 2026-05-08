"""
Question rewriting system to transform generic questions into more specific MPS queries.
Uses both heuristic patterns and LLM-based rephrasing for better knowledge base matching.
"""

from __future__ import annotations

import re
from typing import List, Optional

# MPS-specific term mappings and synonyms
MPS_TERM_MAPPINGS = {
    "benefits": [
        "coverage",
        "indemnity",
        "protection",
        "what is covered",
        "what does mps cover",
        "what does mps provide",
    ],
    "products": [
        "membership",
        "schemes",
        "membership categories",
        "mps offerings",
        "professional protection",
    ],
    "mps products": [
        "medical protection society membership",
        "mps membership",
        "mps indemnity coverage",
    ],
    "costs": [
        "membership fee",
        "premium",
        "pricing",
        "how much does it cost",
        "subscription",
        "annual cost",
    ],
    "how to join": [
        "membership application",
        "how to apply",
        "joining process",
        "application steps",
        "how do i become a member",
    ],
    "requirements": [
        "eligibility",
        "membership criteria",
        "who can join",
        "qualifications",
    ],
    "protection": [
        "indemnity",
        "coverage",
        "defence",
        "claims assistance",
        "legal protection",
    ],
    "help": [
        "support",
        "assistance",
        "guidance",
        "contact mps",
    ],
}

# Generic patterns to detect vague questions
GENERIC_PATTERNS = {
    r"what\s+are\s+the\s+benefits": "benefits",
    r"what.*benefits.*\w+": "benefits",
    r"tell\s+me\s+about": "general info",
    r"what\s+can\s+\w+\s+do": "capabilities",
    r"how\s+do\s+i\s+get": "access",
    r"what.*products": "products",
}


def rewrite_question(question: str) -> List[str]:
    """
    Rewrite a question into multiple more specific variants.
    Returns a list of alternative phrasings, starting with the most specific.
    
    Args:
        question: The original question
        
    Returns:
        List of rewritten question variants (includes original)
    """
    question_lower = question.lower().strip()
    rewrites = [question]  # Always include original
    
    # Check for generic patterns
    for pattern, category in GENERIC_PATTERNS.items():
        if re.search(pattern, question_lower):
            specific_rewrites = _rewrite_by_category(question, category)
            rewrites.extend(specific_rewrites)
            break
    
    # Expand MPS-specific terms
    for generic_term, specific_forms in MPS_TERM_MAPPINGS.items():
        if generic_term in question_lower:
            for specific_form in specific_forms[:2]:  # Top 2 alternatives
                new_question = question_lower.replace(generic_term, specific_form)
                if new_question not in rewrites:
                    rewrites.append(new_question)
    
    # Remove duplicates while preserving order
    seen = set()
    unique_rewrites = []
    for q in rewrites:
        q_normalized = q.lower().strip()
        if q_normalized not in seen:
            seen.add(q_normalized)
            unique_rewrites.append(q)
    
    return unique_rewrites[:5]  # Return top 5 variants


def _rewrite_by_category(original: str, category: str) -> List[str]:
    """Generate specific rewrites based on question category."""
    rewrites = []
    original_lower = original.lower()
    
    if category == "benefits":
        rewrites = [
            "What coverage does MPS membership include?",
            "What does Medical Protection indemnity cover?",
            "What protection does MPS provide to doctors?",
            "What incidents are covered by MPS membership?",
        ]
    elif category == "products":
        rewrites = [
            "What membership categories does MPS offer?",
            "What are the different MPS membership schemes?",
            "What types of professional protection does MPS provide?",
        ]
    elif category == "capabilities":
        rewrites = [
            "How does MPS assist with medicolegal queries?",
            "What support does MPS provide for complaints?",
        ]
    elif category == "access":
        rewrites = [
            "What are the steps to join MPS?",
            "How do I apply for MPS membership?",
            "What is the membership application process?",
        ]
    elif category == "general info":
        rewrites = [
            "What is Medical Protection Society?",
            "How can MPS help medical professionals?",
        ]
    
    return rewrites


def should_rewrite(question: str, retrieved_chunks_count: int, avg_relevance_score: float = 0.0) -> bool:
    """
    Decide if a question should be rewritten based on retrieval confidence.
    
    Args:
        question: The question that was asked
        retrieved_chunks_count: Number of chunks retrieved
        avg_relevance_score: Average relevance score of retrieved chunks
        
    Returns:
        True if question should be rewritten and retried
    """
    # Rewrite if no chunks retrieved
    if retrieved_chunks_count == 0:
        return True
    
    # Rewrite if very low confidence (low score and few matches)
    if retrieved_chunks_count < 3 and avg_relevance_score < 0.3:
        return True
    
    # Rewrite if question is very generic/short with poor retrieval
    if len(question.split()) < 5 and retrieved_chunks_count < 2:
        return True
    
    return False


def get_best_rewrite(question: str) -> str:
    """
    Get the best rewrite of a question (most specific version).
    
    Args:
        question: The original question
        
    Returns:
        The best rewritten version, or original if no rewrites
    """
    rewrites = rewrite_question(question)
    return rewrites[0] if rewrites else question


if __name__ == "__main__":
    # Test examples
    test_questions = [
        "what are the benefits of MPS products?",
        "tell me about MPS",
        "how do I join?",
        "what costs are involved?",
        "How can I switch to MPS?",
    ]
    
    for q in test_questions:
        rewrites = rewrite_question(q)
        print(f"\nOriginal: {q}")
        for i, rw in enumerate(rewrites[1:], 1):
            print(f"  Rewrite {i}: {rw}")
