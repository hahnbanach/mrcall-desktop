"""Email Agent Builder - Generates personalized email extraction agent from user's email patterns.

Analyzes the user's email history to understand:
- Who they engage with (replied emails = VIP contacts)
- What they ignore (cold outreach patterns)
- Their role and business context
- Projects they care about

Then generates a self-contained agent prompt for entity extraction from emails.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import anthropic

from zylch.config import settings
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

3. **PROJECT** - Projects, type of collaborations, products, services, offers etc which are NOT bound to a single PERSON, but can be reproduced for others. E.g. an offer for a certain service can be made for multiple customers, a product sold to different people, a sales agreement with various companies etc.
   #IDENTIFIERS: Name (short descriptive title, e.g., "Product...")
   #ABOUT: A paragraph describing what this PROJECT is
   #HISTORY: Very short description of what happened in this email regarding the PROJECT

=== USER'S PROFILE ===
{user_profile}

=== SAMPLE OF RECENT EMAILS ===
{email_samples}

---

Generate a COMPLETE, SELF-CONTAINED prompt that will extract entities (any number!). Entities MUST be of these 3 entity types

The prompt must include:

1. **USER CONTEXT**
   - Their role and company
   - What projects they care about (sales, support, partnerships, personal)
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
   - Extract PROJECT for the main subject/relationship being discussed, if any. Remember: PROJECTS are generic entities, do not quote other companies in a PROJECT's #ABOUT section!
   - Keep #ABOUT section minimal
   - Put the narrative in #HISTORY
   - Reference people/companies by name in #HISTORY, don't duplicate info

4. **OUTPUT FORMAT**
   Each entity separated by ---ENTITY---, with 3 sections each (#IDENTIFIERS, #ABOUT, #HISTORY):

   ```
   #IDENTIFIERS
   Entity type: person
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
   Entity type: company
   Name: Name of the company
   Website: company.tld

   #ABOUT
   Very short description of the company: particularly what it does if known

   #HISTORY
   Again, which type of communication did the user have with the company?
   
   NB DO NOT CREATE COMPANY entity about USER_COMPANY

   ---ENTITY---
   #IDENTIFIERS
   Entity type: project
   Name: Name of the project

   #ABOUT
   What is it? A collaboration? An offer? A request for work? A candidacy? Anything we should trace over time, eg NOT calls, booking. NO COMPANY EXEPT USER_COMPANY should be quoted here! This section must be very informative: it might be for example
   . a recurrent technical problem -> which kind of email does the user normally send? 
   . an offer -> data about the offer like features, prices, timeline
   . a type of collaboration/sales -> what are the terms of the deals?
   . a product -> features and prices
   All the information above will be used to answer other people asking information about the same project

   #HISTORY
   On this date the user started talking about this project with a `person` or a `company`
   
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


class EmailAgentBuilder:
    """Builds personalized email agent by analyzing user's email patterns."""

    def __init__(
        self,
        storage: SupabaseStorage,
        owner_id: str,
        anthropic_api_key: str,
        user_email: str
    ):
        """Initialize PromptBuilder.

        Args:
            storage: SupabaseStorage instance
            owner_id: Firebase UID
            anthropic_api_key: Anthropic API key for LLM calls
            user_email: User's email address (for identifying sent vs received)
        """
        self.storage = storage
        self.owner_id = owner_id
        self.anthropic = anthropic.Anthropic(api_key=anthropic_api_key)
        self.user_email = user_email.lower() if user_email else ''
        self.user_domain = user_email.split('@')[1].lower() if user_email and '@' in user_email else ''

    def _get_entity_format_suffix(self) -> str:
        """Return the entity format suffix with user_email interpolated."""
        return f"""

---

CRITICAL OUTPUT FORMAT:
- You can extract any amount of entities, and they MUST be one of these 3 types: `person`, `company`, `project`
- In case a single email contains more entities, you must create different sections, each one with its own #IDENTIFIERS, #ABOUT and #HISTORY.
- Each entity is separated by ---ENTITY--- on its own line
- If email is noise/marketing, output only: SKIP

Example: The email is from john@acme.com to {self.user_email} about asking for a meeting. {self.user_email} is the user.

In this case you have 2 `person` (John and the user), 1 `company` (Acme). But because {self.user_email} is the user, they must not be considered as entity to be created/updated.

#IDENTIFIERS
Entity type: person
Name: John Doe
Email: john@acme.com
Company: Acme Corp

#ABOUT
John Doe is the sales director at Acme Corp.

#HISTORY
In December 2025 John reached out to {self.user_email} asking for a meeting about a potential partnership with NewCo.
---ENTITY---
#IDENTIFIERS
Entity type: company
Name: Acme Corp
Website: acme.com

#ABOUT
Acme Corp is a B2B software company specializing in CRM solutions.

#HISTORY
Acme Corp contacted MrCall in December 2025 about a possible partnership.
---ENTITY---
#IDENTIFIERS
Entity type: project
Name: Acme Corp CRM collaboration

#ABOUT
Project to offer our service on Acme's website.

#HISTORY
In December 2025 John Doe from Acme Corp initiated discussions about selling MrCall to their customers.
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

        # Step 1: Get recent emails (100 max, regardless of reply status)
        recent_emails = self._get_recent_emails(limit=100)
        logger.info(f"Found {len(recent_emails)} recent emails")

        # Step 2: Analyze user profile from their sent emails
        user_profile = self._analyze_user_profile(user_domain)
        logger.debug(f"user_profile: {user_profile}")
        # Step 4: Format samples for the meta-prompt (show variety)
        email_samples = self._format_email_samples(recent_emails, max_samples=15)

        # Step 5: Generate the prompt using Claude
        prompt_content = self._generate_prompt(
            user_profile=user_profile,
            email_samples=email_samples
        )

        metadata = {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'user_domain': user_domain,
            'emails_analyzed': len(recent_emails)
        }

        return prompt_content, metadata

    def _get_recent_emails(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent emails regardless of reply status.

        Args:
            limit: Max number of emails to fetch

        Returns:
            List of email dicts, sorted by date (newest first)
        """
        emails = self.storage.get_emails(self.owner_id, limit=limit)
        # Sort by date (newest first)
        emails.sort(key=lambda e: e.get('date_timestamp', 0), reverse=True)
        return emails

    def _analyze_user_profile(self, user_domain: str) -> str:
        """Extract user context from their sent emails.

        Returns a text description of who the user is.
        """
        emails = self.storage.get_emails(self.owner_id, limit=100)

        # Find emails sent BY the user
        user_sent_emails = []
        for email in emails:
            from_email = email.get('from_email', '')
            if user_domain and user_domain in from_email.lower():
                user_sent_emails.append(email)

        if not user_sent_emails:
            return f"User's domain: {user_domain if user_domain else 'unknown'}"

        # Extract signature patterns, common phrases, project
        signatures = []
        projects = []

        for email in user_sent_emails[:20]:  # Sample last 20 sent emails
            body = email.get('body_plain', '') or ''

            # Look for signature (last 200 chars often contain signature)
            if len(body) > 200:
                signature_area = body[-300:]
                signatures.append(signature_area)

            # Collect subjects for projects
            subject = email.get('subject', '')
            if subject:
                projects.append(subject)

        profile_parts = [f"Domain: {user_domain if user_domain else 'unknown'}"]

        if projects:
            profile_parts.append(f"Recent email projects: {', '.join(projects[:10])}")

        if signatures:
            # Just include one signature sample for role detection
            profile_parts.append(f"Signature sample: {signatures[0][:200]}")

        return '\n'.join(profile_parts)

    def _format_email_samples(
        self,
        emails: List[Dict[str, Any]],
        max_samples: int = 10
    ) -> str:
        """Format emails as text samples for the meta-prompt."""
        samples = []

        for i, email in enumerate(emails[:max_samples], 1):
            from_email = email.get('from_email', 'unknown')
            subject = email.get('subject', '(no subject)')
            body = email.get('body_plain', '') or email.get('snippet', '')
            body = body[:500]  # Truncate body

            samples.append(f"""
--- Email {i} ---
From: {from_email}
Subject: {subject}
Body preview: {body}
""")

        return '\n'.join(samples) if samples else "No samples available."

    def _generate_prompt(
        self,
        user_profile: str,
        email_samples: str
    ) -> str:
        """Generate the final extraction prompt using Claude."""
        meta_prompt = EMAIL_AGENT_META_PROMPT.format(
            user_profile=user_profile,
            email_samples=email_samples
        )

        logger.info("Training email analyzer agent...")

        response = self.anthropic.messages.create(
            model=settings.default_model,
            max_tokens=4000,
            messages=[{"role": "user", "content": meta_prompt}]
        )

        prompt_content = response.content[0].text.strip()

        # Append fixed suffix to ensure entity delimiter is always present
        prompt_content += self._get_entity_format_suffix()

        logger.info(f"Generated prompt ({len(prompt_content)} chars)")
        return prompt_content
