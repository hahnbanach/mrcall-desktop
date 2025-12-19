"""Prompt Builder - Generates personalized prompts from user's email patterns.

Analyzes the user's email history to understand:
- Who they engage with (replied emails = VIP contacts)
- What they ignore (cold outreach patterns)
- Their role and business context
- Topics they care about

Then generates a self-contained prompt for memory extraction.
"""

import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import anthropic

from zylch.storage.supabase_client import SupabaseStorage

logger = logging.getLogger(__name__)


# Meta-prompt used to generate the final extraction prompt
META_PROMPT = """You are analyzing a user's email history to create a personalized prompt for their AI assistant.

Your goal: Generate a prompt that will be used to extract relevant information from emails and store it in memory.

=== USER'S PROFILE (inferred from their emails) ===
{user_profile}

=== EMAILS THEY REPLIED TO (high priority - these people matter) ===
{replied_samples}

=== EMAILS THEY IGNORED (low priority - these are noise/cold outreach) ===
{ignored_samples}

=== VIP CONTACTS (frequent correspondence) ===
{vip_contacts}

=== PATTERNS IN IGNORED EMAILS ===
{noise_patterns}

---

Based on this analysis, generate a COMPLETE, SELF-CONTAINED prompt that will be used to extract facts from emails.

The prompt must include:

1. **USER CONTEXT**
   - Their role (founder, engineer, executive, etc.)
   - Their company/domain
   - What they care about professionally
   - What they are NOT (e.g., "NOT an investor" if they ignore fundraising asks)

2. **WHAT TO EXTRACT** (for relevant emails)
   - Contact details (phone, LinkedIn, location)
   - Company and role information
   - Topics discussed and interests
   - Action items and commitments
   - Relationship context

3. **WHAT TO SKIP OR MINIMIZE**
   - Specific cold outreach patterns this user ignores
   - Types of requests they never engage with
   - Newsletter/marketing patterns
   - Be specific based on the ignored emails

4. **VIP TREATMENT**
   - List specific domains/contacts that always deserve detailed extraction
   - These are the user's most engaged contacts

5. **OUTPUT FORMAT**
   The prompt should instruct the LLM to output:
   - Natural language prose (2-5 sentences)
   - "No significant facts." if the email is noise/cold outreach

The generated prompt will receive these template variables:
- {{from_email}} - Sender's email
- {{to_email}} - Recipient(s)
- {{cc_email}} - CC recipients (or "(none)" if empty)
- {{subject}} - Email subject
- {{date}} - Email date
- {{body}} - Email body (truncated)
- {{contact_email}} - The contact being analyzed

OUTPUT ONLY THE PROMPT TEXT. No explanations, no markdown code blocks. Just the prompt itself."""


class PromptBuilder:
    """Builds personalized prompts by analyzing user's email patterns."""

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

        # Step 2: Sample emails - replied vs ignored
        replied_threads = self._get_replied_threads(user_domain, limit=50)
        ignored_emails = self._get_ignored_emails(user_domain, limit=50)

        logger.info(f"Found {len(replied_threads)} replied threads, {len(ignored_emails)} ignored emails")

        # Step 3: Analyze user profile from their sent emails
        user_profile = self._analyze_user_profile(user_domain)

        # Step 4: Identify VIP contacts
        vip_contacts = self._identify_vip_contacts(replied_threads, user_domain)

        # Step 5: Identify noise patterns
        noise_patterns = self._analyze_noise_patterns(ignored_emails)

        # Step 6: Format samples for the meta-prompt
        replied_samples = self._format_email_samples(replied_threads, max_samples=10)
        ignored_samples = self._format_email_samples(ignored_emails, max_samples=10)

        # Step 7: Generate the prompt using Claude
        prompt_content = self._generate_prompt(
            user_profile=user_profile,
            replied_samples=replied_samples,
            ignored_samples=ignored_samples,
            vip_contacts=vip_contacts,
            noise_patterns=noise_patterns
        )

        metadata = {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'user_domain': user_domain,
            'replied_threads_analyzed': len(replied_threads),
            'ignored_emails_analyzed': len(ignored_emails),
            'vip_contacts_count': len(vip_contacts),
            'noise_patterns_count': len(noise_patterns)
        }

        return prompt_content, metadata

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
        replied_samples: str,
        ignored_samples: str,
        vip_contacts: List[str],
        noise_patterns: List[str]
    ) -> str:
        """Generate the final extraction prompt using Claude."""
        vip_text = '\n'.join(f"- {c}" for c in vip_contacts) if vip_contacts else "None identified yet."
        noise_text = '\n'.join(f"- {p}" for p in noise_patterns) if noise_patterns else "None identified yet."

        meta_prompt = META_PROMPT.format(
            user_profile=user_profile,
            replied_samples=replied_samples,
            ignored_samples=ignored_samples,
            vip_contacts=vip_text,
            noise_patterns=noise_text
        )

        logger.info("Generating personalized prompt with Claude...")

        response = self.anthropic.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            messages=[{"role": "user", "content": meta_prompt}]
        )

        prompt_content = response.content[0].text.strip()

        logger.info(f"Generated prompt ({len(prompt_content)} chars)")
        return prompt_content
