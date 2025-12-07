"""Trigger execution service - background worker for event-driven automation.

This service processes queued trigger events and executes user-defined
instructions when events occur (email_received, sms_received, call_received).

Usage:
    # Process pending events (call from cron job, webhook, or manual)
    service = TriggerService()
    await service.process_pending_events()

    # Queue an event (call from webhook handlers)
    await service.queue_event(owner_id, 'call_received', {'caller': '+39123...'})
"""

import logging
from typing import Dict, Any, Optional, List

from zylch.storage.supabase_client import SupabaseStorage as SupabaseClient
from zylch.config import settings

logger = logging.getLogger(__name__)


class TriggerService:
    """Service for processing trigger events in background."""

    def __init__(self):
        self.db = SupabaseClient()

    async def queue_event(
        self,
        owner_id: str,
        event_type: str,
        event_data: Dict[str, Any]
    ) -> Optional[Dict]:
        """Queue an event for background processing.

        Called by webhooks when events occur.

        Args:
            owner_id: Firebase UID of the user
            event_type: email_received, sms_received, call_received
            event_data: Event payload (varies by type)

        Returns:
            Created event record or None
        """
        # Check if user has any active triggers for this event type
        triggers = self.db.get_triggers_by_type(owner_id, event_type)

        if not triggers:
            logger.info(f"No {event_type} triggers for owner {owner_id}, skipping queue")
            return None

        # Queue the event
        event = self.db.queue_trigger_event(owner_id, event_type, event_data)

        if event:
            logger.info(f"Queued {event_type} event {event['id']} for owner {owner_id}")

        return event

    async def process_pending_events(self, limit: int = 10) -> Dict[str, int]:
        """Process pending trigger events.

        Call this from a cron job, scheduler, or after webhook processing.

        Args:
            limit: Max events to process in one batch

        Returns:
            Stats: {'processed': N, 'succeeded': N, 'failed': N}
        """
        stats = {'processed': 0, 'succeeded': 0, 'failed': 0}

        # Get pending events
        events = self.db.get_pending_events(limit=limit)

        if not events:
            logger.debug("No pending trigger events")
            return stats

        logger.info(f"Processing {len(events)} pending trigger events")

        for event in events:
            stats['processed'] += 1

            try:
                # Mark as processing (prevents duplicate processing)
                if not self.db.mark_event_processing(event['id']):
                    logger.warning(f"Event {event['id']} already being processed, skipping")
                    continue

                # Process the event
                result = await self._execute_event(event)

                if result['success']:
                    self.db.mark_event_completed(
                        event['id'],
                        result.get('trigger_id'),
                        result
                    )
                    stats['succeeded'] += 1
                    logger.info(f"Event {event['id']} completed successfully")
                else:
                    self.db.mark_event_failed(event['id'], result.get('error', 'Unknown error'))
                    stats['failed'] += 1
                    logger.error(f"Event {event['id']} failed: {result.get('error')}")

            except Exception as e:
                self.db.mark_event_failed(event['id'], str(e))
                stats['failed'] += 1
                logger.error(f"Event {event['id']} exception: {e}", exc_info=True)

        logger.info(f"Processed {stats['processed']} events: {stats['succeeded']} succeeded, {stats['failed']} failed")
        return stats

    async def _execute_event(self, event: Dict) -> Dict[str, Any]:
        """Execute a single trigger event.

        Args:
            event: Event record from trigger_events table

        Returns:
            {'success': bool, 'trigger_id': str, 'response': str, 'error': str}
        """
        owner_id = event['owner_id']
        event_type = event['event_type']
        event_data = event.get('event_data', {})

        # Get user's triggers for this event type
        triggers = self.db.get_triggers_by_type(owner_id, event_type)

        if not triggers:
            return {
                'success': True,
                'message': f'No active {event_type} triggers'
            }

        # For now, execute the first active trigger
        # TODO: Support multiple triggers per event type
        trigger = triggers[0]

        # Build context message for the agent
        context_message = self._build_context_message(event_type, event_data, trigger['instruction'])

        # Execute via headless agent
        try:
            response = await self._execute_with_agent(owner_id, context_message)

            return {
                'success': True,
                'trigger_id': trigger['id'],
                'instruction': trigger['instruction'],
                'response': response
            }

        except Exception as e:
            return {
                'success': False,
                'trigger_id': trigger['id'],
                'error': str(e)
            }

    def _build_context_message(
        self,
        event_type: str,
        event_data: Dict,
        instruction: str
    ) -> str:
        """Build context message for the agent.

        Args:
            event_type: Type of event
            event_data: Event payload
            instruction: User's trigger instruction

        Returns:
            Formatted message for agent
        """
        if event_type == 'email_received':
            context = f"""A new email was received:
- From: {event_data.get('from', 'Unknown')}
- Subject: {event_data.get('subject', '(no subject)')}
- Preview: {event_data.get('snippet', '')[:200]}

User instruction: {instruction}

Please execute the instruction based on this email."""

        elif event_type == 'sms_received':
            context = f"""A new SMS was received:
- From: {event_data.get('from', 'Unknown')}
- Message: {event_data.get('body', '')}

User instruction: {instruction}

Please execute the instruction based on this SMS."""

        elif event_type == 'call_received':
            context = f"""A phone call was received:
- Caller: {event_data.get('caller', 'Unknown')}
- Duration: {event_data.get('duration_seconds', 0)} seconds
- Transcript: {event_data.get('transcript', '(no transcript)')}

User instruction: {instruction}

Please execute the instruction based on this call."""

        else:
            context = f"""Event: {event_type}
Data: {event_data}

User instruction: {instruction}

Please execute the instruction."""

        return context

    async def _execute_with_agent(self, owner_id: str, message: str) -> str:
        """Execute instruction using headless agent.

        Creates a temporary agent session to execute the trigger instruction.

        Args:
            owner_id: User's Firebase UID
            message: Context message with instruction

        Returns:
            Agent's response
        """
        from zylch.services.chat_service import ChatService

        # Create a headless chat service
        chat_service = ChatService()

        # Process the message (this will initialize agent and execute)
        result = await chat_service.process_message(
            user_message=message,
            user_id=owner_id,
            conversation_history=None,  # Fresh session
            session_id=f"trigger_{owner_id}",
            context={
                'user_id': owner_id,
                'trigger_execution': True  # Flag for logging/tracking
            }
        )

        return result.get('response', '')

    async def get_event_history(self, owner_id: str, limit: int = 20) -> List[Dict]:
        """Get trigger event history for a user.

        Args:
            owner_id: Firebase UID
            limit: Max events to return

        Returns:
            List of events with status and results
        """
        return self.db.get_event_history(owner_id, limit)


# Convenience function for webhook handlers
async def queue_trigger_event(
    owner_id: str,
    event_type: str,
    event_data: Dict[str, Any]
) -> Optional[Dict]:
    """Queue a trigger event (convenience function).

    Usage in webhook handlers:
        from zylch.services.trigger_service import queue_trigger_event
        await queue_trigger_event(owner_id, 'call_received', {'caller': '...'})
    """
    service = TriggerService()
    return await service.queue_event(owner_id, event_type, event_data)


# Function to run from cron/scheduler
async def process_trigger_queue(limit: int = 10) -> Dict[str, int]:
    """Process pending trigger events (for cron/scheduler).

    Usage:
        # In a cron job or scheduler
        from zylch.services.trigger_service import process_trigger_queue
        stats = await process_trigger_queue()
    """
    service = TriggerService()
    return await service.process_pending_events(limit=limit)
