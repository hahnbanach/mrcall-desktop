"""MrCall Memory Agent Trainer - Generates personalized extraction prompt for phone calls.

Analyzes the user's phone call history to understand:
- Types of callers (customers, vendors, partners)
- Common topics and patterns
- What information is worth extracting
- How the AI assistant handled calls

Then generates a self-contained prompt for entity extraction from phone transcriptions.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from zylch.config import settings
from zylch.llm import LLMClient, PROVIDER_MODELS
from zylch.storage.supabase_client import SupabaseStorage

logger = logging.getLogger(__name__)


# Meta-prompt used to generate the MrCall memory extraction agent
MRCALL_MEMORY_META_PROMPT = """You are analyzing a user's phone call history to create a personalized prompt for extracting entities from phone conversations.

Your goal: Generate a prompt that extracts entities from phone call transcriptions handled by an AI voice assistant.

Each entity blob has 3 sections:
- **#IDENTIFIERS**: Stable facts for matching (name, phone, company, etc.)
- **#ABOUT**: One sentence definition (who/what this entity IS) - rarely changes
- **#HISTORY**: Evolving narrative (what's HAPPENING over time) - accumulates with each call

Entity can only be of 3 types:

1. **PERSON** - Who is this caller?
   #IDENTIFIERS: Name (required), Phone number, Email (if mentioned), Company, Role/title
   #ABOUT: One sentence describing their role and relationship
   #HISTORY: What was discussed in this call (e.g., "Called to schedule appointment", "Inquired about pricing")

2. **COMPANY** - What organization does the caller represent?
   #IDENTIFIERS: Name (required), Website (if mentioned), Phone, Address (if mentioned)
   #ABOUT: One sentence describing what the company does
   #HISTORY: What topics were discussed regarding this company

3. **TEMPLATE** - A reusable response pattern - how the AI assistant typically handles certain call types
   #IDENTIFIERS: Name (short descriptive title, e.g., "Appointment Booking", "Price Inquiry Response")
   #ABOUT: Description of what triggers this response and how to handle it
   #HISTORY: Record of calls where this pattern was used

=== BUSINESS CONTEXT ===
{business_profile}

=== SAMPLE PHONE CALLS ===
{call_samples}

---

Generate a COMPLETE, SELF-CONTAINED prompt that will extract entities from phone call transcriptions.

The prompt must include:

1. **BUSINESS CONTEXT**
   - What type of business handles these calls
   - Common call types (appointments, inquiries, complaints, etc.)
   - What information is valuable to extract

2. **CALL FORMAT UNDERSTANDING**
   The transcription will include speaker turns like:
   - "Caller: ..." - The person who called
   - "Assistant: ..." - The AI voice assistant

   Extract information from BOTH sides of the conversation.

3. **EXTRACTION RULES**
   - Extract PERSON for each caller mentioned
   - Extract COMPANY if the caller represents an organization
   - Extract TEMPLATE for recurring call handling patterns
   - Keep #ABOUT section minimal
   - Put the narrative in #HISTORY
   - Note if appointments were made, callbacks requested, or issues resolved

4. **OUTPUT FORMAT**
   Each entity separated by ---ENTITY---, with 3 sections each (#IDENTIFIERS, #ABOUT, #HISTORY):

```
#IDENTIFIERS
Entity type: PERSON
Name: Caller Name
Phone: +1234567890
Company: Company Name if mentioned

#ABOUT
Brief description of who this person is

#HISTORY
Summary of what was discussed in the call, including any action items or follow-ups needed

---ENTITY---
#IDENTIFIERS
Entity type: COMPANY
Name: Company Name
Phone: Company phone if different

#ABOUT
What the company does

#HISTORY
Context of the call regarding this company

---ENTITY---
#IDENTIFIERS
Entity type: TEMPLATE
Name: Call Type Name (e.g., "Appointment Booking", "Service Inquiry")

#ABOUT
Description of this call type and how it should be handled. Include:
- What triggers this type of call
- Key information to collect
- How the assistant typically responds

#HISTORY
Record of calls matching this pattern
```

5. **IMPORTANCE ASSESSMENT**
   - SKIP spam calls, wrong numbers, disconnected calls
   - Extract from: customer inquiries, appointments, business discussions
   - Note any follow-up actions mentioned

The generated prompt will receive these template variables:
- {{contact_phone}} - Caller's phone number
- {{contact_name}} - Caller's name (if known)
- {{call_date}} - When the call happened
- {{call_duration}} - How long the call lasted
- {{conversation}} - The full conversation transcript

OUTPUT ONLY THE PROMPT TEXT. No explanations, no markdown code blocks. Just the prompt itself."""


class MrCallMemoryTrainer:
    """Builds personalized MrCall memory extraction agent by analyzing phone call patterns."""

    def __init__(
        self,
        storage: SupabaseStorage,
        owner_id: str,
        api_key: str,
        user_email: str,
        provider: str
    ):
        """Initialize MrCallMemoryTrainer.

        Args:
            storage: SupabaseStorage instance
            owner_id: Firebase UID
            api_key: LLM API key
            user_email: User's email address
            provider: LLM provider (anthropic, openai, mistral)
        """
        self.storage = storage
        self.owner_id = owner_id
        self.provider = provider
        self.model = PROVIDER_MODELS.get(provider, settings.default_model)
        self.client = LLMClient(api_key=api_key, provider=provider)
        self.user_email = user_email.lower() if user_email else ''
        self.search_limit = 20  # Limit calls to analyze

    def _get_entity_format_suffix(self) -> str:
        """Return the entity format suffix to append to generated prompts."""
        return """

---

CRITICAL OUTPUT FORMAT:
- You can extract any number of entities, and they MUST be one of these 3 types: `PERSON`, `COMPANY`, `TEMPLATE`
- Each entity is separated by ---ENTITY--- on its own line
- If the call is spam/wrong number/disconnected, output only: SKIP
- The output should NOT contain sensitive data like passwords, account numbers, credit cards

Example: A call from +1234567890 (John from Acme Corp) asking about appointment availability for next week.

#IDENTIFIERS
Entity type: PERSON
Name: John
Phone: +1234567890
Company: Acme Corp

#ABOUT
John is a customer from Acme Corp inquiring about services.

#HISTORY
Called on 2025-01-10 to ask about appointment availability for next week. The assistant checked the calendar and offered Thursday at 2pm.

---ENTITY---
#IDENTIFIERS
Entity type: COMPANY
Name: Acme Corp

#ABOUT
Acme Corp is a customer company.

#HISTORY
John from Acme Corp called about scheduling an appointment.

---ENTITY---
#IDENTIFIERS
Entity type: TEMPLATE
Name: Appointment Scheduling

#ABOUT
Standard appointment scheduling call. Caller requests an appointment, assistant checks availability and offers time slots. Key info to collect: preferred date/time, service type, contact details.

#HISTORY
2025-01-10: John from Acme Corp scheduled for Thursday at 2pm.
"""

    async def build_prompt(self) -> Tuple[str, Dict[str, Any]]:
        """Analyze user's phone calls and generate personalized extraction prompt.

        Returns:
            Tuple of (prompt_content, metadata)

        Raises:
            ValueError: If no phone calls found to analyze
        """
        logger.info(f"Building MrCall memory prompt for {self.owner_id}")

        # Get recent phone calls
        calls = self.storage.get_mrcall_conversations(
            self.owner_id,
            limit=self.search_limit,
            days_back=60
        )

        if not calls:
            raise ValueError(
                "No phone calls found. Run `/sync mrcall` first to download transcriptions."
            )

        logger.info(f"Found {len(calls)} calls for analysis")

        # Analyze business profile from calls
        business_profile = self._analyze_business_profile(calls)

        # Format call samples
        call_samples = self._format_call_samples(calls)

        # Generate the prompt
        prompt_content = self._generate_prompt(
            business_profile=business_profile,
            call_samples=call_samples
        )

        metadata = {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'calls_analyzed': len(calls),
            'channel': 'mrcall'
        }

        return prompt_content, metadata

    def _analyze_business_profile(self, calls: List[Dict[str, Any]]) -> str:
        """Analyze patterns in phone calls to understand the business context.

        Args:
            calls: List of phone call records

        Returns:
            Text description of the business profile
        """
        # Count call directions
        total_calls = len(calls)

        # Analyze call durations
        durations = [c.get('call_duration_ms', 0) for c in calls if c.get('call_duration_ms')]
        avg_duration_seconds = (sum(durations) / len(durations) / 1000) if durations else 0

        # Count unique callers
        unique_callers = len(set(
            c.get('contact_phone', '') for c in calls if c.get('contact_phone')
        ))

        # Collect subjects for topic analysis
        subjects = [c.get('subject', '') for c in calls if c.get('subject')]

        # Build profile
        profile_parts = [
            f"Total calls analyzed: {total_calls}",
            f"Unique callers: {unique_callers}",
            f"Average call duration: {int(avg_duration_seconds)} seconds"
        ]

        if subjects:
            profile_parts.append(f"Common call subjects: {', '.join(subjects[:10])}")

        return '\n'.join(profile_parts)

    def _format_call_samples(self, calls: List[Dict[str, Any]], max_samples: int = 10) -> str:
        """Format phone call samples for the meta-prompt.

        Args:
            calls: List of phone call records
            max_samples: Maximum number of samples to include

        Returns:
            Formatted string with call samples
        """
        samples = []

        for i, call in enumerate(calls[:max_samples], 1):
            # Extract conversation from body
            conversation = self._extract_conversation(call.get('body'))

            # Truncate long conversations
            if len(conversation) > 1500:
                conversation = conversation[:1500] + "...[truncated]"

            duration_ms = call.get('call_duration_ms', 0)
            duration_seconds = duration_ms / 1000 if duration_ms else 0

            samples.append(f"""
--- Call {i} ---
Phone: {call.get('contact_phone', 'Unknown')}
Name: {call.get('contact_name', 'Unknown')}
Date: {call.get('call_started_at', 'Unknown')}
Duration: {int(duration_seconds)} seconds
Subject: {call.get('subject', 'N/A')}

Conversation:
{conversation}
""")

        return '\n'.join(samples) if samples else "No call samples available."

    def _extract_conversation(self, body: Any) -> str:
        """Extract conversation text from the call body.

        The body can be a JSON object with various structures depending
        on how MrCall stores the transcription.

        Args:
            body: The body field from mrcall_conversations (can be dict, str, or None)

        Returns:
            Extracted conversation text
        """
        if not body:
            return "(No transcription available)"

        if isinstance(body, str):
            return body

        if isinstance(body, dict):
            # Try common field names for transcription
            for field in ['conversation', 'transcript', 'transcription', 'messages', 'text']:
                if field in body:
                    value = body[field]
                    if isinstance(value, str):
                        return value
                    if isinstance(value, list):
                        # Format message list
                        lines = []
                        for msg in value:
                            if isinstance(msg, dict):
                                speaker = msg.get('speaker', msg.get('role', 'Unknown'))
                                text = msg.get('text', msg.get('content', ''))
                                if text:
                                    lines.append(f"{speaker}: {text}")
                            elif isinstance(msg, str):
                                lines.append(msg)
                        return '\n'.join(lines)
                    if isinstance(value, dict):
                        # Nested structure - try to extract segments
                        if 'segments' in value:
                            return self._format_segments(value['segments'])
                        return str(value)

            # If no known field, try to stringify the whole body
            # but exclude audio markers
            clean_body = {k: v for k, v in body.items() if v != '[AUDIO_STRIPPED]'}
            if clean_body:
                return str(clean_body)

        return "(Could not extract conversation)"

    def _format_segments(self, segments: List[Any]) -> str:
        """Format transcript segments into readable text.

        Args:
            segments: List of transcript segments

        Returns:
            Formatted transcript
        """
        lines = []
        for seg in segments:
            if isinstance(seg, dict):
                speaker = seg.get('speaker', 'Unknown')
                text = seg.get('text', '')
                if text:
                    lines.append(f"{speaker}: {text}")
        return '\n'.join(lines)

    def _generate_prompt(
        self,
        business_profile: str,
        call_samples: str
    ) -> str:
        """Generate the final extraction prompt using LLM.

        Args:
            business_profile: Business context analysis
            call_samples: Formatted call samples

        Returns:
            Generated extraction prompt
        """
        meta_prompt = MRCALL_MEMORY_META_PROMPT.format(
            business_profile=business_profile,
            call_samples=call_samples
        )

        logger.info(f"Training MrCall memory agent (provider: {self.provider})...")
        logger.debug(f"Prompt size: {len(meta_prompt)} chars (~{len(meta_prompt)//4} tokens)")

        response = self.client.create_message_sync(
            model=self.model,
            max_tokens=4000,
            messages=[{"role": "user", "content": meta_prompt}]
        )

        prompt_content = response.content[0].text.strip()

        # Append fixed suffix to ensure entity delimiter is always present
        prompt_content += self._get_entity_format_suffix()

        logger.info(f"Generated MrCall memory prompt ({len(prompt_content)} chars)")
        return prompt_content
