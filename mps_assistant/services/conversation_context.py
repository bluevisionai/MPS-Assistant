"""
Conversation Context Manager

Tracks and manages conversation state including:
- User role/specialty
- Stated concerns
- Previous questions and answers
- Key facts mentioned
- User preferences

This enables context-aware responses that reference prior discussion.
"""

import json
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any


@dataclass
class ConversationContext:
    """Stores contextual information about a conversation."""
    
    user_role: Optional[str] = None
    """User's profession/specialty (e.g., 'GP', 'Specialist', 'Dentist')"""
    
    user_situation: Optional[str] = None
    """User's practice situation (e.g., 'solo', 'group', 'part-time')"""
    
    stated_concerns: List[str] = None
    """Issues user has mentioned (e.g., ['cost', 'eligibility', 'coverage'])"""
    
    previous_questions: List[str] = None
    """Questions asked earlier in conversation"""
    
    previous_answers_summary: List[Dict[str, str]] = None
    """Summary of previous answers: [{"question": "...", "topic": "..."}]"""
    
    key_facts: Dict[str, Any] = None
    """Important facts mentioned: {"specialization": "cardiology", "years_experience": 15}"""
    
    user_preferences: Dict[str, Any] = None
    """Preferences: {"interested_in": "tail_cover", "budget": "low"}"""
    
    last_asked_about: Optional[str] = None
    """Topic of last question (e.g., 'benefits', 'cost', 'application')"""
    
    def __post_init__(self):
        if self.stated_concerns is None:
            self.stated_concerns = []
        if self.previous_questions is None:
            self.previous_questions = []
        if self.previous_answers_summary is None:
            self.previous_answers_summary = []
        if self.key_facts is None:
            self.key_facts = {}
        if self.user_preferences is None:
            self.user_preferences = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConversationContext':
        """Create from dictionary."""
        return cls(**data)
    
    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict())
    
    @classmethod
    def from_json(cls, json_str: str) -> 'ConversationContext':
        """Deserialize from JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)
    
    def get_context_summary(self) -> str:
        """
        Get a human-readable summary of current context for use in prompts.
        
        Returns:
            Multi-line summary of conversation context
        """
        lines = []
        
        if self.user_role:
            lines.append(f"User profession: {self.user_role}")
        
        if self.user_situation:
            lines.append(f"Practice situation: {self.user_situation}")
        
        if self.stated_concerns:
            lines.append(f"Key concerns: {', '.join(self.stated_concerns)}")
        
        if self.previous_answers_summary:
            prev_topics = [p.get("topic", p.get("question", "?")) 
                          for p in self.previous_answers_summary[-3:]]  # Last 3
            lines.append(f"Previously discussed: {', '.join(prev_topics)}")
        
        if self.key_facts:
            facts_str = ", ".join(f"{k}: {v}" for k, v in self.key_facts.items())
            lines.append(f"Key facts: {facts_str}")
        
        if self.user_preferences:
            prefs_str = ", ".join(f"{k}: {v}" for k, v in self.user_preferences.items())
            lines.append(f"Preferences: {prefs_str}")
        
        return "\n".join(lines) if lines else "No context available yet."
    
    def has_context(self) -> bool:
        """Check if any context has been established."""
        return bool(
            self.user_role 
            or self.user_situation
            or self.stated_concerns
            or self.previous_questions
            or self.key_facts
            or self.user_preferences
        )


class ConversationContextExtractor:
    """
    Extracts context information from conversation history.
    Uses patterns and heuristics to infer user details.
    """
    
    # Role keywords mapping
    ROLE_KEYWORDS = {
        'gp': ['gp', 'general practitioner', 'general practice', 'family medicine'],
        'specialist': ['specialist', 'consultant', 'registrar', 'sr doctor'],
        'dentist': ['dentist', 'dental', 'odontologist'],
        'nurse': ['nurse', 'rn', 'registered nurse'],
        'allied_health': ['physiotherapist', 'psychologist', 'therapist', 'allied'],
    }
    
    # Situation keywords
    SITUATION_KEYWORDS = {
        'solo': ['solo', 'sole practitioner', 'solo practice', 'single-handed'],
        'group': ['group', 'partnership', 'group practice', 'associateship'],
        'part_time': ['part-time', 'part time', 'sessional', 'locum'],
        'full_time': ['full-time', 'full time', 'full-time'],
    }
    
    # Concern keywords
    CONCERN_KEYWORDS = {
        'cost': ['cost', 'price', 'fee', 'expensive', 'affordable', 'budget', 'how much'],
        'coverage': ['coverage', 'cover', 'indemnity', 'protection', 'what does it cover'],
        'eligibility': ['eligible', 'eligibility', 'qualify', 'requirements', 'can i'],
        'application': ['apply', 'application', 'join', 'sign up', 'register'],
        'benefits': ['benefits', 'advantage', 'advantage', 'what do i get'],
        'claims': ['claim', 'classed', 'claims process', 'how do i claim'],
    }
    
    @classmethod
    def extract_from_conversation(
        cls,
        questions: List[str],
        current_context: Optional[ConversationContext] = None
    ) -> ConversationContext:
        """
        Extract context from a list of questions/statements.
        
        Args:
            questions: List of user messages from conversation
            current_context: Existing context to build upon
        
        Returns:
            Updated ConversationContext
        """
        context = current_context or ConversationContext()
        
        combined_text = " ".join(questions).lower()
        
        # Extract role
        for role, keywords in cls.ROLE_KEYWORDS.items():
            if any(kw in combined_text for kw in keywords):
                context.user_role = role.replace('_', ' ').title()
                break
        
        # Extract situation
        for situation, keywords in cls.SITUATION_KEYWORDS.items():
            if any(kw in combined_text for kw in keywords):
                context.user_situation = situation.replace('_', ' ').title()
                break
        
        # Extract concerns
        concerns_found = set()
        for concern, keywords in cls.CONCERN_KEYWORDS.items():
            if any(kw in combined_text for kw in keywords):
                concerns_found.add(concern)
        
        if concerns_found:
            context.stated_concerns = sorted(list(concerns_found))
        
        # Store questions
        context.previous_questions = questions[-5:]  # Keep last 5
        
        # Extract year of experience if mentioned
        import re
        years_match = re.search(r'(\d{1,2})\s*years?', combined_text)
        if years_match:
            context.key_facts['years_experience'] = int(years_match.group(1))
        
        return context


class ContextAwarePromptBuilder:
    """
    Builds prompts that incorporate conversation context
    to make responses more personalized and aware of history.
    """
    
    @staticmethod
    def build_context_aware_preamble(
        context: ConversationContext,
        question: str
    ) -> str:
        """
        Build a preamble to add to the system prompt that incorporates context.
        
        Args:
            context: Current conversation context
            question: Current user question
        
        Returns:
            Preamble text to include in system prompt
        """
        if not context.has_context():
            return ""
        
        preamble = "CONVERSATION CONTEXT:\n"
        
        if context.user_role:
            preamble += f"- User is a: {context.user_role}\n"
        
        if context.user_situation:
            preamble += f"- Practice situation: {context.user_situation}\n"
        
        if context.stated_concerns:
            preamble += f"- Key concerns: {', '.join(context.stated_concerns)}\n"
        
        if context.previous_answers_summary:
            preamble += "- Previously discussed:\n"
            for prev in context.previous_answers_summary[-3:]:  # Last 3
                topic = prev.get("topic", prev.get("question", "?"))
                preamble += f"  • {topic}\n"
        
        preamble += "\nRemember to:\n"
        preamble += "1. Reference previous discussion when relevant (e.g., 'As you mentioned...')\n"
        preamble += "2. Avoid repeating information already provided\n"
        preamble += "3. Use appropriate terminology for the user's role\n"
        preamble += "4. Tailor recommendations to their situation\n\n"
        
        return preamble
    
    @staticmethod
    def build_reference_to_previous_answer(
        context: ConversationContext,
        current_question: str
    ) -> Optional[str]:
        """
        If current question relates to previous discussion, generate reference.
        
        Args:
            context: Current conversation context
            current_question: The user's current question
        
        Returns:
            Reference string or None
        """
        if not context.previous_answers_summary:
            return None
        
        question_lower = current_question.lower()
        
        # Check for follow-up patterns
        follow_ups = [
            ("can i still apply" , "application"),
            ("what if i" , "situation"),
            ("like you said" , "previous"),
            ("as you mentioned" , "previous"),
        ]
        
        for phrase, category in follow_ups:
            if phrase in question_lower:
                return f"You're following up on our discussion about {category}. Let me clarify..."
        
        return None
