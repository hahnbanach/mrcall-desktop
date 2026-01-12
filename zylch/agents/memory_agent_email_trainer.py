"""Email Agent Builder - Generates personalized email extraction agent from user's email patterns.

Analyzes the user's email history to understand:
- Who they engage with (replied emails = VIP contacts)
- What they ignore (cold outreach patterns)
- Their role and business context
- Template of email they send

Then generates a self-contained agent prompt for entity extraction from emails.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from zylch.config import settings
from zylch.llm import LLMClient, PROVIDER_MODELS
from zylch.storage.supabase_client import SupabaseStorage

logger = logging.getLogger(__name__)

# Fixed suffix appended to all generated prompts to ensure entity delimiter is used

# Meta-prompt used to generate the email agent
EMAIL_AGENT_META_PROMPT = """You are analyzing a user's email history to create a personalized prompt for their AI assistant.

Your goal: Generate a prompt that extracts entities from emails.

Each entity blob has 3 sections:
- **#IDENTIFIERS**: Stable facts for matching (name, email, website, etc.)
- **#ABOUT**: One sentence definition (who/what this entity IS) - rarely changes
- **#HISTORY**: Evolving narrative (what's HAPPENING over time) - accumulates with each email

Entity can only be of 3 types:

1. **PERSON** - Who is this person?
   #IDENTIFIERS: Name (required), Email, Phone, Company, Role/title
   #ABOUT: One sentence describing their role and company
   #HISTORY: What information we gathered about the company in this email exchange (e.g., "She's looking for a service", "He set up his account")

2. **COMPANY** - What is this organization?
   #IDENTIFIERS: Name (required), Website, Address, VAT/Tax ID
   #ABOUT: One sentence describing what the company does
   #HISTORY: What information we gathered about the company in this email exchange (e.g., "They signed up for a plan", "Started collaboration")

3. **TEMPLATE** - A TEMPLATE is a reusable response pattern - how the user typically responds to a category of inquiries. Extract the user's response style and content for recurring question types so the assistant can draft similar responses.
   #IDENTIFIERS: Name (short descriptive title, e.g., "Product Price", "IT Consulting offer" etc )
   #ABOUT: A paragraph describing what this TEMPLATE is about.
   #HISTORY: Very short description of what happened in this email regarding the template. Eg. 2025-12-22 "The user sent a revised offer for..."

=== USER'S PROFILE ===
{user_profile}

=== SAMPLE OF RECENT EMAILS ===
{email_samples}

---

Generate a COMPLETE, SELF-CONTAINED prompt that will extract entities (any number!). Entities MUST be of these 3 entity types

The prompt must include:

1. **USER CONTEXT**
   - Their role and company
   - What projects they care about (sales, support, partnerships, personal), which kind of email do they send? You need to extract this information in order for other agents to be able to send similar email, with similar content
   - What they ignore (cold outreach, marketing)

2. **USER'S OWN ENTITIES NOT TO BE RE-EXTRACTED**
   The generated prompt MUST include a section listing entities about the email owner themselves, extracted from the analysis above:
   - The user as a PERSON (name, emails, role)
   - The user's COMPANY (name, website, what they do)
   REMEMBER: DO NOT EXTRACT THIS PERSON OR COMPANY ENTITIES!! If you do so, we slow the process and make it useless. 

   This section should say something like:
   "The following entities belong to the email owner. When they appear in emails DO NOT create or update the corresponding blobs:
   - USER_PERSON: [user's name], [user's email], [role] at [company] (DO NOT extract entity describing this person!)
   - USER_COMPANY: [company name], [website], [what they do] (DO NOT extract entity describing this company!)

3. **EXTRACTION RULES**
   - Extract PERSON for each individual mentioned (sender, recipients, people referenced), if any WITH THE EXCEPTION OF THE USER_PERSON: don't extract entity about the USER_PERSON
   - Extract COMPANY for each organization mentioned, if any WITH THE EXCEPTION OF THE USER_COMPANY: don't extract entity about the USER_COMPANY
   - Extract TEMPLATES for the main topic of conversations in the communication. Remember: TEMPLATES are generic entities, do not quote other companies in a TEMPLATES's #ABOUT section!
   - Keep #ABOUT section minimal
   - Put the narrative in #HISTORY
   - Reference people/companies by name in #HISTORY, don't duplicate info

4. **OUTPUT FORMAT**
   Each entity separated by ---ENTITY---, with 3 sections each (#IDENTIFIERS, #ABOUT, #HISTORY):

```
   #IDENTIFIERS
   Entity type: PERSON
   Name: Name Familyname 
   Email: email@example.com
   Company: Company Name if available

   #ABOUT
   About the person: what have you learned about the person reading emails? Where do they work, live, what are their relationship with the user?

   #HISTORY
    What did the person communicate to the user? What the user communicated to them?

NB DO NOT CREATE PERSON entity about USER_PERSON!!

   ---ENTITY---
   #IDENTIFIERS
   Entity type: COMPANY
   Name: Name of the company
   Website: company.tld

   #ABOUT
   Very short description of the company: particularly what it does if known

   #HISTORY
   Again, which type of communication did the user have with the company?
   
   NB DO NOT CREATE COMPANY entity about USER_COMPANY

---ENTITY---
#IDENTIFIERS
Entity type: TEMPLATE
Name: Name of the TEMPLATE (e.g., "Unhandled Call Complaints Response", "Pricing Inquiry Response", "Subscription Cancellation Response")

#ABOUT
A TEMPLATE is a **reusable response pattern** - how the user typically responds to a recurring category of inquiries or situations.

This section should contain:
- **Trigger**: What kind of incoming message triggers this response? (e.g., "Customer asks why they received a certain email from the administration")
- **Response content**: The actual response the user sends, including tone, language, and key points covered
- **Response style**: Formal/informal, language used, signature style

Examples:
- Customer complaint about service issue → User's standard apology + explanation + reassurance template
- Pricing inquiry → User's standard pricing response with features and terms
- Partnership request → User's standard collaboration proposal format
- Technical support question → User's standard troubleshooting response

The goal is to capture HOW the user responds so the assistant can draft similar messages for future inquiries of the same type.

#HISTORY
Record each instance where this response pattern was used:
- 2025-01-08: Sent to customer A regarding complaints about...
- 2025-01-07: Sent to customer B regarding same issue   
```

5. **IMPORTANCE ASSESSMENT**
   - SKIP automated emails, newsletters, marketing
   - Extract from: customer communications, business discussions, personal relationships
   - Judge by email tone and content

The generated prompt will receive these template variables:
- {{from_email}} - Sender's email
- {{to_email}} - Recipient(s)
- {{cc_email}} - CC recipients (or "(none)" if empty)
- {{subject}} - Email subject
- {{date}} - Email date
- {{body}} - Email body (truncated)
- {{contact_email}} - The contact being analyzed

OUTPUT ONLY THE PROMPT TEXT. No explanations, no markdown code blocks. Just the prompt itself."""


class EmailMemoryAgentTrainer:
    """Builds personalized email memory agent by analyzing user's email patterns."""

    def __init__(
        self,
        storage: SupabaseStorage,
        owner_id: str,
        api_key: str,
        user_email: str,
        provider: str
    ):
        """Initialize PromptBuilder.

        Args:
            storage: SupabaseStorage instance
            owner_id: Firebase UID
            api_key: LLM API key
            user_email: User's email address (for identifying sent vs received)
            provider: LLM provider (anthropic, openai, mistral)
        """
        self.storage = storage
        self.owner_id = owner_id
        self.provider = provider
        self.model = PROVIDER_MODELS.get(provider, settings.default_model)
        self.client = LLMClient(api_key=api_key, provider=provider)
        self.user_email = user_email.lower() if user_email else ''
        self.user_domain = user_email.split('@')[1].lower() if user_email and '@' in user_email else ''
        self.search_limit = 20  # Reduced to avoid context window overflow

    def _get_entity_format_suffix(self) -> str:
        """Return the entity format suffix with user_email interpolated."""
        return f"""

---

CRITICAL OUTPUT FORMAT:
- You can extract any amount of entities, and they MUST be one of these 3 types: `PERSON`, `COMPANY`, `TEMPLATE`
- In case a single email contains more entities, you must create different sections, each one with its own #IDENTIFIERS, #ABOUT and #HISTORY.
- Each entity is separated by ---ENTITY--- on its own line
- If email is noise/marketing, output only: SKIP
- The output should NOT contain sensitive data like password, account numbers, credit cards

Example: The email is from john@acme.com to {self.user_email} about asking for a meeting because he finds our IT Consulting Offer too expansive. He also says he is using password 123908kjhkjhHjkh to enter his account, but it does not work. {self.user_email} is the user.

In this case you have 2 `person` (John and the user), 1 `company` (Acme). But because {self.user_email} is the user, they must not be considered as entity to be created/updated.

#IDENTIFIERS
Entity type: PERSON
Name: John Doe
Email: john@acme.com
Company: Acme Corp

#ABOUT
John Doe is the sales director at Acme Corp.

#HISTORY
In December 2025 John reached out to {self.user_email} asking for a meeting about the offer we sent. He also wrote his password does not work. [DOO NOT substitute sensitive data with strings, just do not report them]
---ENTITY---
#IDENTIFIERS
Entity type: COMPANY
Name: Acme Corp
Website: acme.com

#ABOUT
Acme Corp is a B2B software company specializing in CRM solutions.

#HISTORY
Acme Corp contacted MrCall in December 2025 about a possible IT Consulting Offer
---ENTITY---
#IDENTIFIERS
Entity type: TEMPLATE
Name: IT Consulting Offer

#ABOUT
Our company's IT Consulting Offer includes [blah blah blah]. Prices are etc etc. Deliverables are etc etc. ANY USEFUL INFORMATION TO BE EVENTUALLY USED BY THE ASSISTANT FOR WRITING AN EMAIL WITH AN OFFER 

#HISTORY
In December 2025 John Doe from Acme Corp initiated discussions about the offer...
"""

    async def build_memory_email_prompt(self) -> Tuple[str, Dict[str, Any]]:
        """Analyze user's emails and generate personalized extraction prompt.

        Returns:
            Tuple of (prompt_content, metadata)
        """
        logger.info(f"Building memory email prompt for {self.owner_id}")

        # Use user_domain from constructor (derived from user_email parameter)
        user_domain = self.user_domain
        logger.info(f"User email: {self.user_email}, domain: {user_domain}")

        # Step 1: Get recent threads (last email per thread only)
        threads = self._get_recent_threads(limit=self.search_limit)
        logger.info(f"Found {len(threads)} threads for analysis")

        # Step 2: Analyze user profile from their sent emails
        user_profile = self._analyze_user_profile(user_domain)
        logger.debug(f"user_profile: {user_profile}")
        # Step 4: Format samples for the meta-prompt (show variety)
        email_samples = self._format_email_samples(threads)

        # Step 5: Generate the prompt using Claude
        prompt_content = self._generate_prompt(
            user_profile=user_profile,
            email_samples=email_samples
        )

        metadata = {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'user_domain': user_domain,
            'threads_analyzed': len(threads)
        }

        return prompt_content, metadata

    def _get_recent_threads(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent email threads, returning only the last email per thread.

        The last email in a thread typically contains quoted conversation history,
        so we only need to include that one to get full context.

        Args:
            limit: Max number of threads to return

        Returns:
            List of thread dicts with 'emails' key containing only the last email
        """
        # Fetch 3x limit emails to ensure we get enough threads
        emails = self.storage.get_emails(self.owner_id, limit=limit * 3)

        # Group by thread_id
        threads: Dict[str, List[Dict]] = {}
        for email in emails:
            tid = email.get('thread_id', email.get('id', ''))  # Fallback to id if no thread
            if tid:
                if tid not in threads:
                    threads[tid] = []
                threads[tid].append(email)

        # Sort emails within each thread by date
        for tid in threads:
            threads[tid].sort(key=lambda e: e.get('date_timestamp', 0))

        # Sort threads by most recent email
        thread_list = []
        for tid, thread_emails in threads.items():
            if thread_emails:
                most_recent = max(e.get('date_timestamp', 0) for e in thread_emails)
                thread_list.append({
                    'thread_id': tid,
                    'emails': thread_emails,
                    'most_recent': most_recent
                })

        thread_list.sort(key=lambda t: t['most_recent'], reverse=True)

        return thread_list[:limit]

    def _analyze_user_profile(self, user_domain: str) -> str:
        """Extract user context from their sent emails.

        Returns a text description of who the user is.
        """
        emails = self.storage.get_emails(self.owner_id, limit=30)

        # Find emails sent BY the user
        user_sent_emails = []
        for email in emails:
            from_email = email.get('from_email', '')
            if user_domain and user_domain in from_email.lower():
                user_sent_emails.append(email)

        if not user_sent_emails:
            return f"User's domain: {user_domain if user_domain else 'unknown'}"

        # Extract signature and subj
        signatures = []
        subjects = []

        for email in user_sent_emails:
            body = email.get('body_plain', '') or ''

            # Look for signature (last 200 chars often contain signature)
            if len(body) > 200:
                signature_area = body[-300:]
                signatures.append(signature_area)

            # Collect subjects for templates
            subject = email.get('subject', '')
            if subject:
                subjects.append(subject)

        profile_parts = [f"Domain: {user_domain if user_domain else 'unknown'}"]

        if subjects:
            profile_parts.append(f"Recent email subjects: {', '.join(subjects[:20])}")

        if signatures:
            # Just include one signature sample for role detection
            profile_parts.append(f"Signature sample: {signatures[0]}")

        return '\n'.join(profile_parts)

    def _format_email_samples(self, threads: List[Dict[str, Any]]) -> str:
        """Format threads as text samples for the meta-prompt.

        Only includes the last email per thread since it typically contains
        the quoted conversation history.
        """
        samples = []

        for i, thread in enumerate(threads, 1):
            emails = thread.get('emails', [])
            if not emails:
                continue

            # Get subject from first email, but use LAST email for content
            subject = emails[0].get('subject', '(no subject)')
            last_email = emails[-1]  # Last email has the full thread context

            from_email = last_email.get('from_email', 'unknown')
            date = last_email.get('date', 'unknown')
            body = last_email.get('body_plain', '') or last_email.get('snippet', '')

            # Truncate body to avoid context window overflow
            # 20 threads * 12000 chars = 240,000 chars ~= 60k tokens.
            # Safe margin for 200k context.
            if len(body) > 12000:
                body = body[:12000] + "...(truncated)"

            samples.append(f"""
--- Thread {i}: {subject} ({len(emails)} emails) ---
From: {from_email}
Date: {date}
Body: {body}
""")

        return '\n'.join(samples) if samples else "No samples available."

    def _generate_prompt(
        self,
        user_profile: str,
        email_samples: str
    ) -> str:
        """Generate the final extraction prompt using LLM."""
        meta_prompt = EMAIL_AGENT_META_PROMPT.format(
            user_profile=user_profile,
            email_samples=email_samples
        )

        logger.info(f"Training email analyzer agent (provider: {self.provider})...")
        logger.debug(f"Prompt size: {len(meta_prompt)} chars (~{len(meta_prompt)//4} tokens)")

        response = self.client.create_message_sync(
            model=self.model,
            max_tokens=4000,
            messages=[{"role": "user", "content": meta_prompt}]
        )

        prompt_content = response.content[0].text.strip()

        # Append fixed suffix to ensure entity delimiter is always present
        prompt_content += self._get_entity_format_suffix()

        logger.info(f"Generated prompt ({len(prompt_content)} chars)")
        return prompt_content
