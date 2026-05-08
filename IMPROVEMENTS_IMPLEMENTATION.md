# MPS Assistant: Improvement Prioritization Matrix

## Visual Roadmap

```
                        HIGH IMPACT
                            ▲
                            │
                 CONFIDENCE  │  PERSONALIZATION
                 SCORING ●   │   ENGINE ●
                            │
     FEEDBACK  ●            │         GAP DETECTION ●
     LOOP                   │  SMART RECOMMENDATIONS ●
                            │
                 ●           │            ●
            CONVERSATION    │      MULTIMODAL
            MEMORY          │      CONTENT
                            │
                 ●           │      ●
          QUICK SUGGESTIONS │    SESSION
                            │    PERSISTENCE
                            │
     ────────────────────────┼───────────────────────── LOW EFFORT
                   LOW       │       HIGH
                         EFFORT

Legend: ● = Improvement item
        Top-right = Start here (high impact, low effort)
        Top-left = After quick wins (high impact, higher effort)
        Bottom-right = Easy but lower priority
```

---

## Decision Matrix

| Feature | Impact | Effort | Timeline | Priority | ROI |
|---------|--------|--------|----------|----------|-----|
| **Conversation Memory** | 8/10 | 3/10 | 2-3 days | 🔴 **1st** | 4x |
| **Feedback Loop** | 9/10 | 2/10 | 1-2 days | 🔴 **2nd** | 5x |
| **Quick Suggestions** | 7/10 | 2/10 | 1-2 days | 🔴 **3rd** | 3x |
| **Confidence Scoring** | 9/10 | 4/10 | 2-3 days | 🟠 **4th** | 4x |
| **Gap Detection** | 8/10 | 4/10 | 3-4 days | 🟠 **5th** | 3x |
| **Multimodal Content** | 7/10 | 5/10 | 3-4 days | 🟠 **6th** | 3x |
| **Smart Recommendations** | 8/10 | 5/10 | 3-4 days | 🟡 **7th** | 3x |
| **Personalization** | 8/10 | 8/10 | 5-7 days | 🟡 **8th** | 2x |
| **Multi-language** | 6/10 | 8/10 | 5-7 days | 🟢 **9th** | 2x |
| **Human Handoff** | 7/10 | 6/10 | 4-5 days | 🟢 **10th** | 2x |

---

## Quick Implementation Checklist

### Phase 1: This Week (2-3 days)

**[ ] Conversation Memory** 
- [ ] Store conversation context in database
- [ ] Load context on each new message
- [ ] Reference previous answers in responses
- [ ] Test multi-turn conversation flow
- Estimated effort: 2-3 days | Impact: 🔥🔥🔥

**[ ] Feedback Loop**
- [ ] Add 👍👎 buttons after each answer
- [ ] Store feedback in database
- [ ] Create feedback analytics view
- [ ] Alert on negative patterns
- Estimated effort: 1-2 days | Impact: 🔥🔥🔥

**[ ] Quick Answer Suggestions**
- [ ] Generate follow-up questions based on intent
- [ ] Display below each answer
- [ ] Track which suggestions get clicked
- [ ] Optimize suggestions over time
- Estimated effort: 1-2 days | Impact: 🔥🔥

### Phase 2: Next Week (3-4 days)

**[ ] Confidence Scoring**
- [ ] Create scoring algorithm (intent + retrieval + formulation)
- [ ] Add score to each response
- [ ] Escalate when confidence < 0.6
- [ ] Show confidence to users optionally
- Estimated effort: 2-3 days | Impact: 🔥🔥🔥

**[ ] Gap Detection Dashboard**
- [ ] Log unanswered questions
- [ ] Aggregate by category
- [ ] Create dashboard view
- [ ] Send alerts to content team
- Estimated effort: 3-4 days | Impact: 🔥🔥

### Phase 3: Following Week (3-4 days)

**[ ] Multimodal Content**
- [ ] Find related PDFs from KB
- [ ] Link application forms
- [ ] Embed comparison tables
- [ ] Return URLs alongside answers
- Estimated effort: 3-4 days | Impact: 🔥🔥

**[ ] Smart Recommendations**
- [ ] Infer user specialty from conversation
- [ ] Recommend membership category
- [ ] Show reasoning ("Based on your needs...")
- [ ] A/B test different recommendations
- Estimated effort: 3-4 days | Impact: 🔥🔥

---

## Implementation Guide by Feature

### Conversation Memory (Priority #1)

**What to build:**
```python
class ConversationContext:
    - User role / specialty
    - Stated concerns
    - Previous questions
    - Key facts mentioned
    - Preferences
```

**Where to use:**
- Reference in answers: "As you mentioned, you're part-time..."
- Inform recommendations: "For part-time GPs, we recommend..."
- Avoid repetition: "I already explained this earlier..."

**File locations:**
- Frontend: `mps_assistant/static/app.js` - Store context in `uiState`
- Backend: `mps_assistant/services/knowledge_base.py` - Use in `answer_question()`

**Database schema:**
```sql
ALTER TABLE conversations ADD COLUMN context JSON;
-- Store: {"role": "GP", "concerns": ["cost", "eligibility"]}
```

---

### Feedback Loop (Priority #2)

**UI Addition:**
```html
<div class="answer-feedback">
  [Answer text...]
  
  <div class="feedback-buttons">
    Was this helpful?
    <button onclick="recordFeedback(answerId, true)">👍 Yes</button>
    <button onclick="recordFeedback(answerId, false)">👎 No</button>
  </div>
  
  <div id="feedback-text" class="hidden">
    <textarea placeholder="Tell us how we can improve..."></textarea>
    <button>Send Feedback</button>
  </div>
</div>
```

**Backend:**
```python
# POST /api/feedback
@app.post("/api/feedback")
async def record_feedback(feedback: FeedbackRequest):
    await db.store_feedback({
        "answer_id": feedback.answer_id,
        "helpful": feedback.helpful,
        "comment": feedback.comment,
    })
    return {"status": "recorded"}
```

**Analytics:**
```python
# Track which answers have poor feedback
poor_answers = await db.query("""
    SELECT answer_id, COUNT(*) as negative_count
    FROM feedback
    WHERE helpful = false
    GROUP BY answer_id
    HAVING negative_count > 3
    ORDER BY negative_count DESC
""")

# Alert content team
for answer in poor_answers:
    notify_team(f"Answer {answer.id} needs review ({answer.negative_count} complaints)")
```

---

### Confidence Scoring (Priority #4)

**Algorithm:**
```python
def calculate_confidence(intent_score, retrieval_score, formulation_score):
    """
    Weighted confidence score
    """
    confidence = (
        intent_score * 0.3 +      # How well did we understand?
        retrieval_score * 0.5 +   # How good are the sources?
        formulation_score * 0.2   # How relevant is the response?
    )
    
    if confidence >= 0.75:
        return {"level": "HIGH", "action": "ANSWER", "emoji": "✅"}
    elif confidence >= 0.6:
        return {"level": "MEDIUM", "action": "WARN", "emoji": "⚠️"}
    elif confidence >= 0.4:
        return {"level": "LOW", "action": "ESCALATE", "emoji": "❓"}
    else:
        return {"level": "VERY_LOW", "action": "ESCALATE", "emoji": "❌"}
```

**Scoring sources:**
```python
# Intent score = how clear was the user intent
intent_score = intent_analysis.confidence_score  # 0-1

# Retrieval score = how good were the matches
retrieval_score = (
    len(retrieved_chunks) / 6 *  # Did we find enough?
    avg_chunk_score              # How good are they?
)
max(0, min(1, retrieval_score))

# Formulation score = how well did LLM address intent
formulation_score = 0.8  # For now, assume good if retrieved content exists
```

**UI Response:**
```
✅ HIGH CONFIDENCE
[Answer text...]
Sources: [1] [2] [3]
───────────────────────

⚠️ MEDIUM CONFIDENCE  
[Answer text...]
Sources: [1] [2]
🤝 Need clarification? Chat with an agent
───────────────────────

❓ LOW CONFIDENCE
We're not confident about this answer.

🤝 Would you like to speak with an expert?
[Connect with Agent] [Rephrase Question]
```

---

## Quick Metrics Dashboard

### After Implementing Phase 1:

```
MPS Assistant Metrics (This Week)

Conversations: 127
- Questions asked: 342
- Avg questions per session: 2.7
- Sessions with feedback: 64 (50%)

Feedback Summary:
- Helpful: 52 (81%)
- Not helpful: 12 (19%)
- Comments provided: 8

Top Questions:
1. "How to apply?" (23 mentions)
2. "What does membership cost?" (18 mentions)
3. "Can I switch providers?" (14 mentions)

Unanswered Questions Detected:
- "What if I make a mistake on the application?" (4 mentions)
- "How do I cancel membership?" (3 mentions)

Suggestion: Create FAQ for these 2 topics
```

---

## Risk Assessment & Mitigations

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| Context data leaks | Low | High | Encrypt stored context, GDPR compliance |
| Performance degradation | Medium | Medium | Cache intent analysis, optimize queries |
| False confidence scores | Medium | Medium | Validate with user feedback, fine-tune weights |
| Information overload (too many suggestions) | Low | Low | Limit to 3 suggestions, prioritize best |
| Feedback spam | Low | Low | Rate limit, require explanation for negative |

---

## Success Criteria

### After Phase 1 (Week 1-2)
- ✅ Conversations feel more natural (member feedback)
- ✅ Can measure answer quality (feedback data)
- ✅ Members guided to relevant topics (suggestion CTR > 30%)
- ✅ Confidence issues caught early (escalation < 10%)

### After Phase 2 (Week 3-4)
- ✅ Content gaps visible in dashboard
- ✅ KB prioritization data-driven
- ✅ Members see personalized recommendations

### After Phase 3 (Week 5-6)
- ✅ More complete answers (multimodal content)
- ✅ Application starts +20%
- ✅ Support tickets -30%

---

## Technical Dependencies

Before starting, ensure:
- [ ] Database connections working
- [ ] Session storage implemented
- [ ] LLM API stable
- [ ] Frontend can handle dynamic UI updates

## Next Steps

1. **Read IMPROVEMENTS_ROADMAP.md** (this file)
2. **Pick Phase 1 items** (Conversation Memory + Feedback Loop)
3. **Estimate actual effort** for your team
4. **Create tickets** in project management tool
5. **Start coding** 🚀
