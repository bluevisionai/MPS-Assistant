# Three-Stage Semantic Intelligence Pipeline

## Overview

The MPS Assistant now uses an **AI-powered three-stage pipeline** to understand what users are really asking, find the best content, and formulate intelligent responses.

```
User Question
     ↓
[Stage 1: Intent Analysis] - AI understands true intent
     ↓
[Stage 2: Semantic Retrieval] - Uses intent to find better content
     ↓
[Stage 3: Response Formulation] - AI crafts answer addressing intent
     ↓
Intelligent Answer with Sources
```

## Architecture

### Stage 1: Intent Analysis

**Purpose:** Understand what the user really wants to know, not just what they literally asked.

**Process:**
1. LLM analyzes the question and conversation context
2. Extracts semantic intent and underlying needs
3. Generates implied questions user might have
4. Identifies key search terms and retrieval hints

**Example:**
```
User asks: "What are the benefits of MPS products?"

Intent Analysis discovers:
- Primary intent: "Understand what MPS membership covers"
- Implied questions: 
  - "What is included in membership?"
  - "What protection do I get?"
- Semantic keywords: ["coverage", "indemnity", "membership", "protection"]
- Retrieval hints: ["Look for membership benefits and coverage details"]
```

**API:**
```python
from mps_assistant.services.semantic_intent import SemanticIntentAnalyzer

analyzer = SemanticIntentAnalyzer(llm_service)
intent = analyzer.analyze_intent(
    question="What are the benefits of MPS products?",
    conversation_history=messages
)

# Returns IntentAnalysis with:
# - primary_intent
# - implied_questions[]
# - semantic_keywords[]
# - retrieval_hints[]
```

### Stage 2: Semantic Retrieval

**Purpose:** Find better matching content using the extracted intent.

**Process:**
1. Builds an enriched query combining:
   - Original question
   - Primary intent
   - Semantic keywords
   - Implied questions
2. Performs semantic search with enriched query
3. Compares results to original query
4. Uses best results (original or enriched)

**Example:**
```
Original query: "benefits of mps products"
→ Gets 0-2 low-scoring matches

Enriched query: "coverage indemnity membership protection what protection do I get what is included in membership?"
→ Gets 6-8 high-scoring matches

Result: Uses enriched results
```

**Configuration:**
```python
# Only use enriched results if they're significantly better
if enriched_score > original_score * 0.8:
    use_enriched_results()
```

### Stage 3: Response Formulation

**Purpose:** Generate answers that address the user's true intent, not just literal question.

**Process:**
1. LLM receives:
   - Original question
   - User's underlying intent
   - Related questions they might have
   - Retrieved relevant content
2. Formulates response addressing the intent
3. Includes citations from source material
4. Provides practical guidance

**Example:**
```
Question: "What are the benefits of MPS products?"
Intent: "Understand what MPS membership covers"
Related: "What protection do I get?" "What incidents are covered?"

Retrieved content: [6 chunks about MPS coverage, indemnity, membership benefits]

Response formulates answer that:
✓ Explains MPS membership coverage
✓ Addresses protection concerns
✓ Provides practical next steps
✓ Cites sources [1], [2], [3]
```

**API:**
```python
from mps_assistant.services.semantic_intent import EnrichedResponseFormulator

formulator = EnrichedResponseFormulator(llm_service)
answer = formulator.formulate_response(
    question="What are the benefits of MPS products?",
    intent_analysis=intent,
    retrieved_chunks=content,
    conversation_history=messages
)
```

## Debug Output

When processing a question, the system logs each stage:

```
[SEMANTIC] Analyzing intent for: What are the benefits of MPS...
[SEMANTIC] Intent: Intent: Understand MPS coverage | Keywords: coverage, indemnity, membership, protection
[SEMANTIC] Enriched query: What are the benefits of MPS products? coverage indemnity...
[SEMANTIC] Enriched score: 0.78 vs original: 0.15
[SEMANTIC] Using enriched retrieval results
[SEMANTIC] Using enriched response formulation
```

This helps you understand how each question is being processed.

## Fallback Behavior

If any stage fails:
- **Intent Analysis fails** → Uses question as-is
- **Enriched Retrieval fails** → Uses original retrieval
- **Response Formulation fails** → Falls back to standard LLM

System always returns an answer, gracefully degrading if needed.

## Performance Implications

### Extra API Calls
- **Stage 1:** 1 LLM call to analyze intent (~100-300 tokens)
- **Stage 2:** Retrieval only (no new LLM call)
- **Stage 3:** 1 LLM call to formulate response (~300-500 tokens)

**Total:** 2 LLM calls per question (vs. 1 for standard flow)

### Typical Response Time
- Intent analysis: ~0.5-1 second
- Enriched retrieval: ~0.2-0.5 seconds
- Response formulation: ~0.8-1.5 seconds
- **Total:** 1.5-3 seconds (human-acceptable)

### When to Use

✅ **Use semantic pipeline for:**
- Generic/vague questions
- Complex multi-part questions
- Questions implying related concerns
- First-time users with unclear intents

⚡ **Optimizations considered:**
- Cache intent analyses (same question → same intent)
- Batch intent analysis (multiple questions)
- Async retrieval (parallel semantic + lexical search)

## Configuration

### Adjust Intent Analysis

In `semantic_intent.py`:
```python
def _build_intent_messages(self, question, history):
    # Modify prompt for different intent extraction styles
    # Temperature: 0.3 (deterministic) - 0.7 (creative)
    # Max tokens: adjust for depth
```

### Adjust Retrieval Threshold

```python
# Only accept enriched results if reasonably close
if enriched_score > original_score * 0.8:  # <- Adjust threshold
    use_enriched()
```

### Adjust Response Formulation

```python
# Modify system prompt for tone/style
"You are MPS Assistant. Answer based ONLY on provided excerpts..."
```

## Example Scenarios

### Scenario 1: Generic Question

```
User: "What are the benefits of MPS products?"

Stage 1: Discovers user wants to understand membership value
Stage 2: Finds specific coverage and indemnity content
Stage 3: Provides comprehensive answer addressing value proposition

Result: ✅ Confident answer instead of refusal
```

### Scenario 2: Follow-up Question

```
Previous: "How do I join MPS?"
User: "What happens if I make a mistake?"

Stage 1: Understands user fears about application mistakes
Stage 2: Finds content about applications, mistakes, support
Stage 3: Addresses concern + provides reassurance

Result: ✅ Contextual answer addressing anxiety
```

### Scenario 3: Complex Intent

```
User: "Is MPS good for part-time doctors?"

Stage 1: Extracts three intents:
  - Eligibility (can part-time doctors join?)
  - Suitability (does MPS offer what part-timers need?)
  - Value (is it worth it for part-time practice?)

Stage 2: Retrieves content covering all three aspects
Stage 3: Addresses all three concerns in response

Result: ✅ Comprehensive answer, not just literal response
```

## Monitoring & Analytics

Track pipeline effectiveness:

```python
# Log what percentage use enriched retrieval
enriched_usage = retrieval_changes / total_questions

# Log response formulation usage
formulation_usage = formulated_responses / total_questions

# Track performance by question category
[intent_keywords] → avg_response_time, user_satisfaction
```

## Future Enhancements

1. **Intent Caching:** Store analyzed intents for common questions
2. **Multi-turn Understanding:** Track intent evolution across conversation
3. **Confidence Scoring:** Rate how well responses address intent
4. **Implicit Intent Learning:** Learn what users really want over time
5. **Custom Pipelines:** Different pipelines for different user roles (doctors, students, etc.)
