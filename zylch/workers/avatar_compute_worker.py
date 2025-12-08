"""Background worker for avatar computation.

Runs as Railway cron job every 5 minutes.
Processes avatar_compute_queue in batches.
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Dict

import anthropic

from zylch.config import settings
from zylch.services.avatar_aggregator import AvatarAggregator
from zylch.storage.supabase_client import SupabaseStorage

logger = logging.getLogger(__name__)


class AvatarComputeWorker:
    """Background worker for avatar computation.

    Runs as Railway cron job every 5 minutes.
    Processes avatar_compute_queue in batches.
    """

    def __init__(
        self,
        storage: SupabaseStorage,
        anthropic_client: anthropic.Anthropic,
        batch_size: int = 10
    ):
        """Initialize worker.

        Args:
            storage: Supabase storage client
            anthropic_client: Anthropic API client
            batch_size: Number of avatars to process per batch
        """
        self.storage = storage
        self.anthropic = anthropic_client
        self.aggregator = AvatarAggregator(storage)
        self.batch_size = batch_size

    async def run_once(self):
        """Process one batch from queue.

        Called by Railway cron: */5 * * * *
        """
        logger.info("Avatar compute worker starting...")

        # Fetch batch from queue (ordered by priority)
        try:
            batch = self.storage.client.table('avatar_compute_queue')\
                .select('*')\
                .order('priority', desc=True)\
                .order('scheduled_at', desc=False)\
                .limit(self.batch_size)\
                .execute()

            if not batch.data:
                logger.info("No avatars to compute")
                return

            logger.info(f"Processing {len(batch.data)} avatars...")

            for item in batch.data:
                try:
                    await self._process_avatar(item)
                except Exception as e:
                    logger.error(f"Error processing {item['contact_id']}: {e}")
                    self._handle_retry(item)

            logger.info(f"Batch complete: {len(batch.data)} avatars updated")

        except Exception as e:
            logger.error(f"Failed to fetch queue: {e}")

    async def _process_avatar(self, queue_item: Dict):
        """Process single avatar from queue.

        Args:
            queue_item: Queue entry with owner_id, contact_id, trigger_type, priority
        """
        start_time = datetime.now(timezone.utc)
        contact_id = queue_item['contact_id']
        owner_id = queue_item['owner_id']

        logger.info(f"Processing avatar: {contact_id} (trigger: {queue_item['trigger_type']})")

        # 1. Build context (NO LLM - just data aggregation)
        context = self.aggregator.build_context(
            owner_id=owner_id,
            contact_id=contact_id
        )

        # 2. Call Claude ONCE for relationship analysis
        analysis = await self._analyze_relationship(context)

        # 3. Update avatar in database
        avatar_data = {
            'owner_id': owner_id,
            'contact_id': contact_id,
            'display_name': analysis.get('contact_name', context['display_name']),
            'identifiers': context['identifiers'],
            'relationship_summary': analysis['relationship_summary'],
            'relationship_status': analysis['status'],
            'relationship_score': analysis['priority'],
            'suggested_action': analysis.get('action'),
            'interaction_summary': {
                'thread_count': context['thread_count'],
                'email_count': context['email_count'],
                'last_interaction': context['threads'][0]['date'] if context['threads'] else None
            },
            'preferred_tone': analysis.get('preferred_tone', 'professional'),
            'response_latency': context['response_latency'],
            'relationship_strength': context['relationship_strength'],
            'last_computed': datetime.now(timezone.utc).isoformat(),
            'compute_trigger': queue_item['trigger_type'],
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        # Upsert avatar
        self.storage.client.table('avatars').upsert(
            avatar_data,
            on_conflict='owner_id,contact_id'
        ).execute()

        # 4. Generate embedding for semantic search (using sentence-transformers)
        # TODO: Implement embedding generation
        # embedding = self._generate_embedding(analysis['relationship_summary'])
        # self.storage.update_avatar_embedding(owner_id, contact_id, embedding)

        # 5. Remove from queue
        self.storage.client.table('avatar_compute_queue')\
            .delete()\
            .eq('id', queue_item['id'])\
            .execute()

        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        logger.info(f"✓ Updated avatar for {contact_id} in {duration:.1f}s")

    async def _analyze_relationship(self, context: Dict) -> Dict:
        """Analyze relationship using Claude.

        This is the ONLY LLM call in the avatar computation flow.

        Args:
            context: Aggregated context from AvatarAggregator

        Returns:
            Dict with:
            - contact_name: Display name
            - relationship_summary: Narrative summary
            - status: 'open', 'waiting', 'closed'
            - priority: 1-10
            - action: Suggested next step
            - preferred_tone: 'formal', 'casual', 'professional'
        """
        prompt = self._build_avatar_prompt(context)

        try:
            response = self.anthropic.messages.create(
                model=settings.default_model,
                max_tokens=1500,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            # Parse response
            content = response.content[0].text
            return self._parse_analysis(content, context)

        except Exception as e:
            logger.error(f"Failed to analyze relationship: {e}")
            # Return fallback analysis
            return self._fallback_analysis(context)

    def _build_avatar_prompt(self, context: Dict) -> str:
        """Build prompt for relationship analysis.

        Args:
            context: Aggregated context

        Returns:
            Prompt string for Claude
        """
        # Build thread summaries
        thread_summaries = []
        for t in context['threads'][:10]:
            thread_summaries.append(
                f"- {t.get('date', 'Unknown date')}: {t.get('subject', 'No subject')} "
                f"({t.get('from_email', 'Unknown sender')})"
            )

        threads_text = "\n".join(thread_summaries) if thread_summaries else "No recent emails"

        # Build calendar summaries
        event_summaries = []
        for e in context['calendar_events'][:5]:
            event_summaries.append(
                f"- {e.get('start_time', 'Unknown date')}: {e.get('summary', 'No title')}"
            )

        events_text = "\n".join(event_summaries) if event_summaries else "No recent meetings"

        prompt = f"""Analyze this professional relationship and provide a concise summary.

**Contact:** {context['display_name']}
**Emails:** {', '.join(context['identifiers']['emails'])}

**Communication Stats:**
- Email threads: {context['thread_count']}
- Total emails: {context['email_count']}
- Emails per week: {context['communication_frequency']['emails_per_week']}
- Recent meetings: {context['communication_frequency']['events_per_month']}
- Last contact: {context['communication_frequency'].get('last_contact_days_ago', 'Unknown')} days ago
- Relationship strength: {context['relationship_strength']:.2f}/1.0

**Recent Email Threads (last 10):**
{threads_text}

**Recent Meetings (last 5):**
{events_text}

**Response Time:**
{context['response_latency'] or 'Insufficient data'}

---

Please provide:
1. **Name:** Best guess for their name (if different from {context['display_name']})
2. **Summary:** 2-3 sentence narrative of the relationship context and recent interactions
3. **Status:** One of:
   - "open" - needs action from me (I need to respond/follow up)
   - "waiting" - waiting for them (I responded, ball in their court)
   - "closed" - no action needed (conversation complete or no pending items)
4. **Priority:** 1-10 score (10 = most urgent/important)
5. **Action:** Suggested next step (or "No action needed")
6. **Tone:** Their preferred communication style: "formal", "casual", or "professional"

Format your response as:
NAME: [name]
SUMMARY: [relationship summary]
STATUS: [open/waiting/closed]
PRIORITY: [1-10]
ACTION: [suggested action]
TONE: [formal/casual/professional]
"""

        return prompt

    def _parse_analysis(self, content: str, context: Dict) -> Dict:
        """Parse Claude's response into structured data.

        Args:
            content: Raw response from Claude
            context: Original context (for fallback)

        Returns:
            Parsed analysis dict
        """
        try:
            # Simple regex parsing
            import re

            name_match = re.search(r'NAME:\s*(.+?)(?:\n|$)', content, re.IGNORECASE)
            summary_match = re.search(r'SUMMARY:\s*(.+?)(?:\nSTATUS:|$)', content, re.IGNORECASE | re.DOTALL)
            status_match = re.search(r'STATUS:\s*(open|waiting|closed)', content, re.IGNORECASE)
            priority_match = re.search(r'PRIORITY:\s*(\d+)', content)
            action_match = re.search(r'ACTION:\s*(.+?)(?:\nTONE:|$)', content, re.IGNORECASE | re.DOTALL)
            tone_match = re.search(r'TONE:\s*(formal|casual|professional)', content, re.IGNORECASE)

            return {
                'contact_name': name_match.group(1).strip() if name_match else context['display_name'],
                'relationship_summary': summary_match.group(1).strip() if summary_match else content[:500],
                'status': status_match.group(1).lower() if status_match else 'unknown',
                'priority': int(priority_match.group(1)) if priority_match else 5,
                'action': action_match.group(1).strip() if action_match else None,
                'preferred_tone': tone_match.group(1).lower() if tone_match else 'professional'
            }

        except Exception as e:
            logger.warning(f"Failed to parse analysis: {e}")
            return self._fallback_analysis(context)

    def _fallback_analysis(self, context: Dict) -> Dict:
        """Generate fallback analysis when LLM fails.

        Args:
            context: Aggregated context

        Returns:
            Basic analysis dict
        """
        return {
            'contact_name': context['display_name'],
            'relationship_summary': f"Contact with {context['email_count']} emails across {context['thread_count']} threads.",
            'status': 'unknown',
            'priority': 5,
            'action': 'Review manually',
            'preferred_tone': 'professional'
        }

    def _handle_retry(self, item: Dict):
        """Handle failed avatar computation with exponential backoff.

        Args:
            item: Queue item that failed
        """
        retry_count = item.get('retry_count', 0) + 1

        if retry_count >= 3:
            # Max retries exceeded - remove from queue
            self.storage.client.table('avatar_compute_queue')\
                .delete()\
                .eq('id', item['id'])\
                .execute()
            logger.warning(f"✗ Max retries exceeded for {item['contact_id']}")
        else:
            # Schedule retry with exponential backoff
            delay_hours = 2 ** retry_count  # 2h, 4h, 8h
            scheduled_at = datetime.now(timezone.utc) + timedelta(hours=delay_hours)

            self.storage.client.table('avatar_compute_queue')\
                .update({
                    'retry_count': retry_count,
                    'scheduled_at': scheduled_at.isoformat()
                })\
                .eq('id', item['id'])\
                .execute()

            logger.info(f"↻ Retry {retry_count}/3 for {item['contact_id']} in {delay_hours}h")


# CLI entry point for Railway cron
async def main():
    """Main entry point for Railway cron job."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    logger.info("="*60)
    logger.info("Avatar Compute Worker Starting")
    logger.info("="*60)

    # Initialize services
    storage = SupabaseStorage.get_instance()

    anthropic_client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key
    )

    worker = AvatarComputeWorker(storage, anthropic_client, batch_size=10)

    # Run one batch
    await worker.run_once()

    logger.info("="*60)
    logger.info("Avatar Compute Worker Complete")
    logger.info("="*60)


if __name__ == "__main__":
    asyncio.run(main())
