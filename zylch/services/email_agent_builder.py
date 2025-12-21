"""Email Agent Builder - Generates personalized email extraction agent from user's email patterns.

Analyzes the user's email history to understand:
- Who they engage with (replied emails = VIP contacts)
- What they ignore (cold outreach patterns)
- Their role and business context
- Topics they care about

Then generates a self-contained agent prompt for entity extraction from emails.
"""

import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import anthropic

from zylch.storage.supabase_client import SupabaseStorage

logger = logging.getLogger(__name__)

# Fixed suffix appended to all generated prompts to ensure entity delimiter is used
ENTITY_FORMAT_SUFFIX = """

---

CRITICAL OUTPUT FORMAT:
- Extract exactly 3 types: person, company, topic
- Separate each with ---ENTITY--- on its own line
- PERSON and COMPANY blobs: minimal identifiers + 1 sentence #About
- TOPIC blobs: the full narrative, referencing people/companies by name
- If email is noise/marketing, output only: SKIP

Example:
#Identifiers
Entity type: person
Name: John Doe
Email: john@example.com
Company: Acme Corp

#About
John Doe is the sales director at Acme Corp.
---ENTITY---
#Identifiers
Entity type: company
Name: Acme Corp
Website: acme.com

#About
Acme Corp is a software company.
---ENTITY---
#Identifiers
Entity type: topic
Name: Acme Corp partnership discussion

#About
In December 2025 John Doe from Acme Corp reached out about a potential partnership. He is interested in integrating MrCall with their CRM system.
"""

# Meta-prompt used to generate the email agent
EMAIL_AGENT_META_PROMPT = """You are analyzing a user's email history to create a personalized prompt for their AI assistant.

Your goal: Generate a prompt that extracts THREE types of entities from emails:

1. **PERSON** - Who is this person?
   - Name (required)
   - Email (if available)
   - Phone (if available)
   - Company they work for (if known)
   - Role/title (if known)

   The #About section should be 1 sentence max: their role and company.

2. **COMPANY** - What is this organization?
   - Name (required)
   - Website (if available)
   - Address (if available)
   - VAT/Tax ID (if available)

   The #About section should be 1 sentence max: what the company does.

3. **TOPIC** - What is the relationship/story about?
   - Name: A short descriptive title (e.g., "MrCall integration for PC Dépannage", "Barcelona trip December 2025")

   The #About section contains the narrative: what happened, when, who was involved (reference by name), current status, next steps.

=== USER'S PROFILE ===
{user_profile}

=== SAMPLE OF RECENT EMAILS ===
{email_samples}

=== FREQUENT CONTACTS ===
{frequent_contacts}

---

Generate a COMPLETE, SELF-CONTAINED prompt that will extract these 3 entity types.

The prompt must include:

1. **USER CONTEXT**
   - Their role and company
   - What topics they care about (sales, support, partnerships, personal)
   - What they ignore (cold outreach, marketing)

2. **USER'S OWN ENTITIES**
   The generated prompt MUST include a section listing entities about the email owner themselves, extracted from the analysis above:
   - The user as a PERSON (name, emails, role)
   - The user's COMPANY (name, website, what they do)
   - The user's PRODUCTS/SERVICES as TOPIC entities

   This section should say something like:
   "The following entities belong to the email owner. When they appear in emails, create or update the corresponding blobs:
   - PERSON: [user's name], [user's email], [role] at [company]
   - COMPANY: [company name], [website], [what they do]
   - TOPIC: [product/service name] - [brief description]"

3. **EXTRACTION RULES**
   - Extract PERSON for each individual mentioned (sender, recipients, people referenced)
   - Extract COMPANY for each organization mentioned
   - Extract TOPIC for the main subject/relationship being discussed
   - Keep PERSON and COMPANY blobs minimal (identifiers + 1 sentence)
   - Put the narrative in TOPIC blobs
   - Reference people/companies by name in topics, don't duplicate info

4. **OUTPUT FORMAT**
   Each entity separated by ---ENTITY---:

   ```
   #Identifiers
   Entity type: person
   Name: Francesco Spina
   Email: francesco.spina@tiscali.it
   Company: Tiscali

   #About
   Francesco Spina is a business development manager at Tiscali.
   ---ENTITY---
   #Identifiers
   Entity type: company
   Name: Tiscali
   Website: tiscali.it

   #About
   Tiscali is an Italian telecommunications company.
   ---ENTITY---
   #Identifiers
   Entity type: topic
   Name: Tiscali partnership opportunity

   #About
   In 2024 Mario initiated contact with Tiscali about integrating MrCall. Francesco Spina is the main contact. In December 2025 Mario sent a signed contract to Francesco.
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

        # Step 3: Identify frequent contacts
        frequent_contacts = self._identify_frequent_contacts(recent_emails, user_domain)

        # Step 4: Format samples for the meta-prompt (show variety)
        email_samples = self._format_email_samples(recent_emails, max_samples=15)

        # Step 5: Generate the prompt using Claude
        prompt_content = self._generate_prompt(
            user_profile=user_profile,
            email_samples=email_samples,
            frequent_contacts=frequent_contacts
        )

        metadata = {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'user_domain': user_domain,
            'emails_analyzed': len(recent_emails),
            'frequent_contacts_count': len(frequent_contacts)
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

    def _identify_frequent_contacts(
        self,
        emails: List[Dict[str, Any]],
        user_domain: str
    ) -> List[str]:
        """Identify contacts with most email activity.

        Returns list of email addresses with frequent correspondence.
        """
        contact_counts: Counter = Counter()

        for email in emails:
            from_email = email.get('from_email', '')
            if from_email and (not user_domain or user_domain not in from_email.lower()):
                contact_counts[from_email.lower()] += 1

        # Return top contacts (at least 2 emails)
        frequent = [email for email, count in contact_counts.most_common(20) if count >= 2]
        return frequent

    def _get_replied_threads(self, user_domain: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get email threads where the user replied (high-value relationships).

        These represent contacts the user actively engages with.
        """
        # Strategy: Find threads where there are multiple emails,
        # and at least one email is FROM the user's domain (indicating they replied)
        # Fetch 300 emails - enough to get ~100 threads for analysis
        emails = self.storage.get_emails(self.owner_id, limit=300)

        # Group by thread_id
        threads: Dict[str, List[Dict]] = {}
        for email in emails:
            tid = email.get('thread_id', '')
            if tid:
                if tid not in threads:
                    threads[tid] = []
                threads[tid].append(email)

        # Find threads where user sent at least one email
        replied_threads = []
        for tid, thread_emails in threads.items():
            user_sent = False
            external_emails = []

            for email in thread_emails:
                from_email = email.get('from_email', '')
                if user_domain and user_domain in from_email.lower():
                    user_sent = True
                else:
                    external_emails.append(email)

            # If user sent something AND there are external emails, this is a replied thread
            if user_sent and external_emails:
                # Use the most recent external email as the sample
                external_emails.sort(key=lambda e: e.get('date_timestamp', 0), reverse=True)
                replied_threads.append(external_emails[0])

        # Sort by date and limit
        replied_threads.sort(key=lambda e: e.get('date_timestamp', 0), reverse=True)
        return replied_threads[:limit]

    def _get_ignored_emails(self, user_domain: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get emails the user never replied to (potential noise/cold outreach).

        These represent contacts/patterns the user ignores.
        """
        # Fetch 300 emails - enough to get ~100 threads for analysis
        emails = self.storage.get_emails(self.owner_id, limit=300)

        # Group by thread_id
        threads: Dict[str, List[Dict]] = {}
        for email in emails:
            tid = email.get('thread_id', '')
            if tid:
                if tid not in threads:
                    threads[tid] = []
                threads[tid].append(email)

        # Find threads where user never sent anything
        ignored_emails = []
        for tid, thread_emails in threads.items():
            user_sent = False

            for email in thread_emails:
                from_email = email.get('from_email', '')
                if user_domain and user_domain in from_email.lower():
                    user_sent = True
                    break

            # If user never sent anything, all emails in this thread were ignored
            if not user_sent and thread_emails:
                # Use the most recent email as the sample
                thread_emails.sort(key=lambda e: e.get('date_timestamp', 0), reverse=True)
                ignored_emails.append(thread_emails[0])

        # Sort by date and limit
        ignored_emails.sort(key=lambda e: e.get('date_timestamp', 0), reverse=True)
        return ignored_emails[:limit]

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

        # Extract signature patterns, common phrases, topics
        signatures = []
        topics = []

        for email in user_sent_emails[:20]:  # Sample last 20 sent emails
            body = email.get('body_plain', '') or ''

            # Look for signature (last 200 chars often contain signature)
            if len(body) > 200:
                signature_area = body[-300:]
                signatures.append(signature_area)

            # Collect subjects for topics
            subject = email.get('subject', '')
            if subject:
                topics.append(subject)

        profile_parts = [f"Domain: {user_domain if user_domain else 'unknown'}"]

        if topics:
            profile_parts.append(f"Recent email topics: {', '.join(topics[:10])}")

        if signatures:
            # Just include one signature sample for role detection
            profile_parts.append(f"Signature sample: {signatures[0][:200]}")

        return '\n'.join(profile_parts)

    def _identify_vip_contacts(
        self,
        replied_threads: List[Dict[str, Any]],
        user_domain: str
    ) -> List[str]:
        """Identify high-engagement contacts (VIPs).

        Returns list of email addresses/domains with highest engagement.
        """
        # Count how many times user replied to each contact
        contact_counts: Counter = Counter()

        for email in replied_threads:
            from_email = email.get('from_email', '')
            if from_email and (not user_domain or user_domain not in from_email.lower()):
                contact_counts[from_email.lower()] += 1

        # Return contacts with 2+ interactions
        vips = [email for email, count in contact_counts.most_common(20) if count >= 2]
        return vips

    def _analyze_noise_patterns(self, ignored_emails: List[Dict[str, Any]]) -> List[str]:
        """Identify common patterns in ignored emails.

        Returns list of pattern descriptions.
        """
        patterns = []

        # Analyze sender domains
        sender_domains: Counter = Counter()
        for email in ignored_emails:
            from_email = email.get('from_email', '')
            if '@' in from_email:
                domain = from_email.split('@')[1].lower()
                sender_domains[domain] += 1

        # Domains that appear frequently in ignored emails
        for domain, count in sender_domains.most_common(5):
            if count >= 3:
                patterns.append(f"Emails from {domain} (ignored {count} times)")

        # Analyze subject patterns
        subjects = [e.get('subject', '') for e in ignored_emails if e.get('subject')]

        # Common words in ignored subjects
        subject_words: Counter = Counter()
        for subject in subjects:
            for word in subject.lower().split():
                if len(word) > 4:  # Skip short words
                    subject_words[word] += 1

        # Words that appear frequently in ignored subjects
        common_words = [word for word, count in subject_words.most_common(10) if count >= 3]
        if common_words:
            patterns.append(f"Common words in ignored subjects: {', '.join(common_words)}")

        # Check for fundraising patterns
        fundraising_signals = ['raising', 'series', 'investor', 'fund', 'investment', 'pitch']
        fundraising_count = sum(
            1 for e in ignored_emails
            if any(s in (e.get('body_plain', '') or e.get('subject', '')).lower() for s in fundraising_signals)
        )
        if fundraising_count >= 3:
            patterns.append(f"Fundraising/investment asks ({fundraising_count} ignored)")

        # Check for sales patterns
        sales_signals = ['demo', 'schedule a call', 'would love to', 'partnership', 'collaborate']
        sales_count = sum(
            1 for e in ignored_emails
            if any(s in (e.get('body_plain', '') or '').lower() for s in sales_signals)
        )
        if sales_count >= 3:
            patterns.append(f"Sales/partnership outreach ({sales_count} ignored)")

        return patterns

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
        email_samples: str,
        frequent_contacts: List[str]
    ) -> str:
        """Generate the final extraction prompt using Claude."""
        contacts_text = '\n'.join(f"- {c}" for c in frequent_contacts) if frequent_contacts else "None identified yet."

        meta_prompt = EMAIL_AGENT_META_PROMPT.format(
            user_profile=user_profile,
            email_samples=email_samples,
            frequent_contacts=contacts_text
        )

        logger.info("Training email analyzer agent...")

        response = self.anthropic.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            messages=[{"role": "user", "content": meta_prompt}]
        )

        prompt_content = response.content[0].text.strip()

        # Append fixed suffix to ensure entity delimiter is always present
        prompt_content += ENTITY_FORMAT_SUFFIX

        logger.info(f"Generated prompt ({len(prompt_content)} chars)")
        return prompt_content
