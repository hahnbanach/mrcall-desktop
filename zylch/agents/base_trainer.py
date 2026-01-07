"""Base Agent Trainer - Shared logic for all agent trainers.

Provides common initialization, email fetching, and LLM prompt generation
to eliminate duplication across agent trainers.

All trainers (EmailerAgentTrainer, EmailMemoryAgentTrainer, EmailTaskAgentTrainer)
should inherit from this base class.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from zylch.config import settings
from zylch.llm import LLMClient, PROVIDER_MODELS
from zylch.storage.supabase_client import SupabaseStorage

logger = logging.getLogger(__name__)


class BaseAgentTrainer:
    """Base class for all agent trainers with shared initialization and methods."""

    def __init__(
        self,
        storage: SupabaseStorage,
        owner_id: str,
        api_key: str,
        user_email: str,
        provider: str
    ):
        """Initialize base trainer with common configuration.

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
        self.user_domain = (
            user_email.split('@')[1].lower()
            if user_email and '@' in user_email
            else ''
        )

    def _get_emails(
        self,
        limit: int = 100,
        filter_sent: bool = False
    ) -> List[Dict[str, Any]]:
        """Get emails from storage, optionally filtering for sent only.

        Args:
            limit: Max number of emails to fetch
            filter_sent: If True, only return emails sent BY the user

        Returns:
            List of email dicts, sorted by date (newest first)
        """
        all_emails = self.storage.get_emails(self.owner_id, limit=limit * 2 if filter_sent else limit)

        if filter_sent and self.user_domain:
            # Filter to only sent emails
            emails = []
            for email in all_emails:
                from_email = email.get('from_email', '').lower()
                if self.user_domain in from_email:
                    emails.append(email)
            emails = emails[:limit]
        else:
            emails = all_emails[:limit]

        # Sort by date (newest first)
        emails.sort(key=lambda e: e.get('date_timestamp', 0), reverse=True)
        return emails

    def _get_blobs(
        self,
        entity_type: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get memory blobs from storage, optionally filtering by entity type.

        Args:
            entity_type: Filter by type (PERSON, COMPANY, TEMPLATE) or None for all
            limit: Max number of blobs to return

        Returns:
            List of blob dicts
        """
        result = self.storage.client.table('blobs').select('*').eq('owner_id', self.owner_id)

        if entity_type:
            result = result.ilike('content', f'%Entity type: {entity_type}%')

        result = result.order('updated_at', desc=True).limit(limit).execute()
        return result.data if result.data else []

    def _generate_prompt(
        self,
        meta_prompt: str,
        max_tokens: int = 4000
    ) -> str:
        """Generate a prompt by calling the LLM with a meta-prompt.

        Args:
            meta_prompt: The meta-prompt (with variables already formatted)
            max_tokens: Max tokens for LLM response

        Returns:
            Generated prompt content
        """
        logger.info(f"Generating agent prompt (provider: {self.provider})...")

        response = self.client.create_message_sync(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": meta_prompt}]
        )

        prompt_content = response.content[0].text.strip()
        logger.info(f"Generated prompt ({len(prompt_content)} chars)")
        return prompt_content

    def _format_email_samples(
        self,
        emails: List[Dict[str, Any]],
        max_samples: int = 15,
        body_limit: int = 500
    ) -> str:
        """Format emails as text samples for meta-prompts.

        Args:
            emails: List of email dicts
            max_samples: Max number of samples to include
            body_limit: Max chars of body to include per email

        Returns:
            Formatted string with email samples
        """
        samples = []

        for i, email in enumerate(emails, 1):
            from_email = email.get('from_email', 'unknown')
            to_emails = email.get('to_email', [])
            if isinstance(to_emails, list):
                to_str = ', '.join(to_emails)
            else:
                to_str = str(to_emails)

            subject = email.get('subject', '(no subject)')
            body = email.get('body_plain', '') or email.get('snippet', '')
            body = body

            samples.append(f"""
--- Email {i} ---
From: {from_email}
To: {to_str}
Subject: {subject}
Body:
{body}
""")

        return '\n'.join(samples) if samples else "No email samples available."

    def _analyze_user_profile(self, sent_emails: List[Dict[str, Any]]) -> str:
        """Extract user profile from their sent emails.

        Analyzes greetings, signatures, subjects, and language patterns.

        Args:
            sent_emails: List of emails sent by the user

        Returns:
            Text description of user's profile
        """
        patterns = {
            'greetings': [],
            'signoffs': [],
            'subjects': [],
            'avg_length': 0,
            'languages': set()
        }

        for email in sent_emails:
            body = email.get('body_plain', '') or ''
            subject = email.get('subject', '')

            # Extract greeting (first line)
            lines = body.strip().split('\n')
            if lines:
                first_line = lines[0].strip()
                if len(first_line) < 100:
                    patterns['greetings'].append(first_line)

            # Extract sign-off (last 300 chars)
            if len(body) > 200:
                patterns['signoffs'].append(body[-300:])

            # Subject patterns
            if subject:
                patterns['subjects'].append(subject)

            # Language detection (simple heuristic)
            italian_markers = ['ciao', 'salve', 'buongiorno', 'gentile', 'cordiali', 'saluti', 'grazie']
            if any(m in body.lower() for m in italian_markers):
                patterns['languages'].add('Italian')
            else:
                patterns['languages'].add('English')

            patterns['avg_length'] += len(body)

        if sent_emails:
            patterns['avg_length'] //= len(sent_emails)

        # Build profile text
        profile_parts = [
            f"Domain: {self.user_domain}",
            f"Average email length: {patterns['avg_length']} chars",
            f"Languages detected: {', '.join(patterns['languages']) if patterns['languages'] else 'Unknown'}",
        ]

        if patterns['greetings']:
            unique_greetings = list(set(patterns['greetings']))
            profile_parts.append(f"Greeting patterns: {', '.join(unique_greetings)}")

        if patterns['signoffs']:
            profile_parts.append(f"Signature sample:\n{patterns['signoffs'][0]}")

        if patterns['subjects']:
            profile_parts.append(f"Subject patterns: {', '.join(patterns['subjects'])}")

        return '\n'.join(profile_parts)

    def _build_metadata(self, **extra) -> Dict[str, Any]:
        """Build standard metadata dict for storing with the prompt.

        Args:
            **extra: Additional metadata fields to include

        Returns:
            Metadata dict with generated_at, user_domain, and any extra fields
        """
        metadata = {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'user_domain': self.user_domain,
        }
        metadata.update(extra)
        return metadata

    async def build_prompt(self) -> Tuple[str, Dict[str, Any]]:
        """Build the agent prompt. Must be implemented by subclasses.

        Returns:
            Tuple of (prompt_content, metadata)

        Raises:
            NotImplementedError: If not overridden by subclass
        """
        raise NotImplementedError("Subclasses must implement build_prompt()")
