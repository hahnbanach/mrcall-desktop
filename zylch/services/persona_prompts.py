"""Prompts for persona extraction from conversations."""

EXTRACTION_PROMPT = """Analyze this conversation between a user and Zylch AI assistant.
Extract NEW facts about the USER (not about their contacts).

Categories to extract:
1. RELATIONSHIPS: Personal/professional relationships mentioned
   - Family members, friends, colleagues, partners
   - Include any contact details mentioned (email, phone)
   - Format: "relationship_type: name (details if any)"

2. PREFERENCES: Communication and work preferences
   - Email style, tone, timing preferences
   - Decision-making patterns
   - Language preferences

3. WORK_CONTEXT: Professional context
   - Role, company, industry
   - Key clients, projects, responsibilities
   - Business relationships

4. PATTERNS: Behavioral patterns observed
   - How they use Zylch
   - Recurring requests or habits
   - Time-based patterns (when they work, respond, etc.)

IMPORTANT:
- Extract facts about THE USER, not about their contacts
- Be specific and include details when available
- Only include facts that are clearly stated or strongly implied
- Do not infer or assume facts not supported by the conversation

CONVERSATION:
{conversation}

Return ONLY new, concrete facts in JSON format:
{{
  "relationships": ["fact1", "fact2"],
  "preferences": ["fact1"],
  "work_context": ["fact1"],
  "patterns": ["fact1"]
}}

If no new facts found, return empty arrays.
Do NOT include markdown code blocks, return raw JSON only.
"""

# Categories for memory storage
PERSONA_CATEGORIES = [
    "relationships",
    "preferences",
    "work_context",
    "patterns"
]

# Category descriptions for prompt building
CATEGORY_DESCRIPTIONS = {
    "relationships": "Personal and professional relationships",
    "preferences": "Communication and work preferences",
    "work_context": "Professional context and role",
    "patterns": "Behavioral patterns and habits"
}
