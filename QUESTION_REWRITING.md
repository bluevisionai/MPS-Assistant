# Question Rewriting System

## Overview

The MPS Assistant now includes a smart question rewriting system that automatically transforms generic or vague questions into more specific queries that match the knowledge base content.

## How It Works

### 1. **Detection Phase**
When a user asks a question, the system first checks if it's generic or vague by looking for patterns like:
- "what are the benefits"
- "tell me about"
- "what can ... do"
- "how do I get"

### 2. **Primary Retrieval**
The system tries to retrieve content with the original question.

### 3. **Confidence Check**
If retrieval confidence is low (no matches found, or very few low-scoring matches), the system triggers rewriting.

### 4. **Automatic Rewriting**
For example, "what are the benefits of MPS products?" is automatically expanded to:
- "What coverage does MPS membership include?"
- "What does Medical Protection indemnity cover?"
- "What protection does MPS provide to doctors?"
- "What incidents are covered by MPS membership?"

### 5. **Smart Selection**
The system tries each rewritten variant and uses whichever one returns the best matching content.

## Example Flow

**User asks:** "What are the benefits of MPS products?"

**System actions:**
1. ❌ Original retrieval finds weak matches (confidence: 0.2)
2. 🔄 Detects generic "benefits" question
3. 🔄 Tries rewrite: "What coverage does MPS membership include?"
4. ✅ Gets strong matches (confidence: 0.8)
5. 📤 Uses the rewritten question results to answer

**User sees:** Confident answer with proper MPS sources cited

## MPS-Specific Mappings

The system understands MPS terminology:

| Generic Term | MPS Equivalent |
|---|---|
| benefits | coverage, indemnity, protection |
| products | membership, schemes, membership categories |
| costs | membership fee, premium, pricing |
| how to join | membership application, application steps |
| protection | indemnity, defence, claims assistance |
| help | support, assistance, guidance |

## Configuration

Adjust rewriting thresholds in `question_rewriter.py`:

```python
def should_rewrite(question: str, retrieved_chunks_count: int, avg_relevance_score: float = 0.0) -> bool:
    # Rewrite if no chunks retrieved
    if retrieved_chunks_count == 0:
        return True
    
    # Rewrite if very low confidence
    if retrieved_chunks_count < 3 and avg_relevance_score < 0.3:
        return True
    
    # Rewrite if question is very generic/short
    if len(question.split()) < 5 and retrieved_chunks_count < 2:
        return True
    
    return False
```

## Debug Output

When enabled, the system logs rewriting attempts:

```
[DEBUG] Original question: what are the benefits of MPS products?
[DEBUG] Retrieved 0 chunks
[DEBUG] Retrieval confidence low. Trying rewrites...
[DEBUG] Trying rewritten question: What coverage does MPS membership include?
[DEBUG]   Got 6 chunks (avg score: 0.78)
[DEBUG] Using rewritten question (better results)
```

View this in server logs to troubleshoot retrieval issues.

## Adding Custom Patterns

To add new question patterns, edit `MPS_TERM_MAPPINGS` in `question_rewriter.py`:

```python
MPS_TERM_MAPPINGS = {
    "new_generic_term": [
        "specific_form_1",
        "specific_form_2",
    ],
}
```

Or add pattern matching:

```python
GENERIC_PATTERNS = {
    r"your_pattern_here": "category_name",
}
```

## Benefits

- ✅ Handles vague questions automatically
- ✅ Improves retrieval confidence
- ✅ No extra API calls (uses heuristics first)
- ✅ Transparent to users (they see the best answer)
- ✅ MPS-aware term mapping
- ✅ Fallback mechanism if rewrites fail

## Future Enhancements

1. **LLM-based rewriting**: Use GPT to generate context-aware rewrites
2. **Learning from interactions**: Track which rewrites work best
3. **User feedback loop**: Improve mappings based on member interactions
4. **Multi-language support**: Translate questions to match knowledge base language
