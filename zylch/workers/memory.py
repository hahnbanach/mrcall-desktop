"""Memory Agent - Extract facts from emails and store in entity-centric blobs.

Processes emails to extract relationship information about contacts,
storing in blobs with reconsolidation (merging with existing knowledge).

Uses hybrid search (FTS + semantic) to find existing blobs about the same entity,
then LLM-merges new information with existing knowledge.
"""

import logging
from typing import Dict, List, Optional

from zylch.llm import LLMClient
from zylch.storage import Storage
from zylch.memory import (
    BlobStorage,
    HybridSearchEngine,
    LLMMergeService,
    EmbeddingEngine,
    MemoryConfig,
)

logger = logging.getLogger(__name__)


class MemoryWorker:
    """Worker for extracting facts from emails and storing in entity-centric blobs.

    Flow:
    1. Extract facts from email about the contact
    2. Search for existing blob about this entity (hybrid search)
    3. If found: LLM-merge new facts with existing knowledge
    4. If not found: create new blob
    5. Mark email as processed
    """

    def __init__(self, storage: Storage, owner_id: str, api_key: str, provider: str):
        """Initialize MemoryWorker.

        Args:
            storage: Storage instance
            owner_id: Owner ID for namespace
            api_key: API key for the LLM provider
            provider: LLM provider (anthropic, openai, mistral)
        """
        self.storage = storage
        self.owner_id = owner_id
        self.namespace = f"user:{owner_id}"

        # BYOK - API key must be provided, no env var fallback
        if not api_key:
            raise ValueError(
                f"API key required for memory extraction. "
                f"Please run `/connect {provider}` to configure your API key."
            )

        # Initialize components
        config = MemoryConfig()
        self.embedding_engine = EmbeddingEngine(config)
        from zylch.storage.database import get_session

        self.blob_storage = BlobStorage(get_session, self.embedding_engine)
        self.hybrid_search = HybridSearchEngine(get_session, self.embedding_engine)
        self.llm_merge = LLMMergeService(api_key, provider)

        # LLM client for fact extraction
        self.client = LLMClient(api_key=api_key, provider=provider)

        # Cache for user's custom prompt (lazy loaded)
        self._custom_prompt: Optional[str] = None
        self._custom_prompt_loaded: bool = False

        logger.info(f"MemoryWorker initialized for namespace={self.namespace}")

    def _get_extraction_prompt(self) -> Optional[str]:
        """Get extraction prompt - user-specific only.

        Loads user's custom prompt from DB on first call, caches for subsequent calls.
        Returns None if no custom prompt exists (user must run /agent train email first).

        Returns:
            The extraction prompt, or None if not configured
        """
        if not self._custom_prompt_loaded:
            raw = self.storage.get_agent_prompt(
                self.owner_id, "memory_email",
            )
            # Treat empty string as None
            self._custom_prompt = (
                raw if raw and raw.strip() else None
            )
            self._custom_prompt_loaded = True

            if self._custom_prompt:
                logger.info(
                    "Using user's custom memory_email prompt",
                )
            else:
                logger.debug(
                    "No custom prompt found — will auto-train",
                )

        return self._custom_prompt

    def has_custom_prompt(self) -> bool:
        """Check if user has a custom extraction prompt."""
        if not self._custom_prompt_loaded:
            self._get_extraction_prompt()
        return self._custom_prompt is not None

    async def process_email(self, email: Dict) -> bool:
        """Process single email to extract and store entities.

        Each email may contain multiple entities (people, companies, etc.).
        Each entity is stored as a separate blob with reconsolidation.

        Args:
            email: Email dict with id, from_email, to_email, subject, body_plain, date

        Returns:
            True if processed successfully, False otherwise
        """
        email_id = email.get("id", "unknown")
        try:
            logger.info(f"Processing email {email_id}")

            # Determine the contact (the other party, not the user)
            from_email = email.get("from_email", "")
            to_emails = email.get("to_email", [])
            if isinstance(to_emails, str):
                to_emails = [to_emails]

            # Contact is whoever is not the user
            # For now, use from_email as the contact (most common case: incoming email)
            contact_email = from_email
            if not contact_email:
                logger.warning(f"No contact email for {email_id}")
                # Still mark as processed so we don't retry
                self.storage.mark_email_processed(self.owner_id, email_id)
                return True

            # Step 1: Extract entities from email (may be multiple)
            entities = self._extract_entities(email, contact_email)
            if not entities:
                logger.debug(f"No entities extracted from {email_id}")
                # Still mark as processed so we don't retry
                self.storage.mark_email_processed(self.owner_id, email_id)
                return True

            logger.debug(f"Extracted {len(entities)} entities from email {email_id}")

            # Step 2: Process each entity separately
            event_desc = f"Extracted from email {email_id} ({email.get('date', 'unknown date')})"

            for i, entity_content in enumerate(entities):
                await self._upsert_entity(
                    entity_content, event_desc, email_id, i + 1, len(entities)
                )

            # Step 3: Mark email as processed
            self.storage.mark_email_processed(self.owner_id, email_id)
            return True

        except Exception as e:
            logger.error(f"Error processing email {email_id}: {e}", exc_info=True)
            return False

    async def _upsert_entity(
        self,
        entity_content: str,
        event_desc: str,
        email_id: str,
        entity_num: int,
        total_entities: int,
    ) -> None:
        """Upsert a single entity blob with reconsolidation.

        Args:
            entity_content: The entity blob content
            event_desc: Event description for the blob
            email_id: Source email ID (for logging)
            entity_num: Which entity this is (1-indexed)
            total_entities: Total entities from this email
        """
        logger.info(f"Upserting entity, searching with:\n{entity_content}\n\n")

        # Get top 3 candidates above threshold
        existing_blobs = self.hybrid_search.find_candidates_for_reconsolidation(
            owner_id=self.owner_id, content=entity_content, namespace=self.namespace, limit=3
        )

        upserted = False

        for existing in existing_blobs:
            # Try to merge with this candidate
            logger.debug(
                f"Trying to merge with blob {existing.blob_id} (score={existing.hybrid_score:.2f})"
            )
            merged_content = self.llm_merge.merge(existing.content, entity_content)

            # If LLM says INSERT (entities don't match), try next candidate
            if "INSERT" in merged_content.upper() and len(merged_content) < 10:
                logger.debug(f"Skipping blob {existing.blob_id} - entities don't match")
                continue

            # Successful merge
            self.blob_storage.update_blob(
                blob_id=existing.blob_id,
                owner_id=self.owner_id,
                content=merged_content,
                event_description=event_desc,
            )
            logger.info(
                f"Reconsolidated blob {existing.blob_id} with email {email_id} (entity {entity_num}/{total_entities})"
            )
            upserted = True
            break

        if not upserted:
            # No suitable blob found, create new
            blob = self.blob_storage.store_blob(
                owner_id=self.owner_id,
                namespace=self.namespace,
                content=entity_content,
                event_description=event_desc,
            )
            logger.info(
                f"Created new blob {blob['id']} from email {email_id} (entity {entity_num}/{total_entities})"
            )

    async def process_batch(
        self, emails: List[Dict], concurrency: int = 5,
    ) -> int:
        """Process batch of emails with parallel LLM calls.

        Uses asyncio.Semaphore to limit concurrency.
        Stops on 3 consecutive failures (auth errors etc.).

        Args:
            emails: List of email dicts
            concurrency: Max parallel LLM calls (default 5)

        Returns:
            Number of successfully processed emails
        """
        import asyncio

        logger.info(
            f"Processing batch of {len(emails)} emails"
            f" (concurrency={concurrency})",
        )
        sem = asyncio.Semaphore(concurrency)
        processed = 0
        failures = 0
        stop = False

        async def _process_one(email: Dict):
            nonlocal processed, failures, stop
            if stop:
                return
            async with sem:
                if stop:
                    return
                success = await self.process_email(email)
                if success:
                    processed += 1
                    failures = 0
                else:
                    failures += 1
                    if failures >= 3:
                        logger.error(
                            "3 consecutive failures — stopping"
                            " batch (check API key)",
                        )
                        stop = True

        await asyncio.gather(
            *[_process_one(e) for e in emails],
            return_exceptions=True,
        )
        logger.info(
            f"Batch complete:"
            f" {processed}/{len(emails)} processed",
        )
        return processed

    def _format_email_data(
        self, email: Dict, contact_email: str,
    ) -> str:
        """Format email fields as plain text for LLM."""
        body = (
            email.get("body_plain", "")
            or email.get("snippet", "")
        )
        cc_raw = email.get("cc_email") or email.get("cc") or []
        if isinstance(cc_raw, list):
            cc = ", ".join(cc_raw) if cc_raw else "(none)"
        else:
            cc = cc_raw if cc_raw else "(none)"
        to = (
            ", ".join(email.get("to_email", []))
            if isinstance(email.get("to_email"), list)
            else email.get("to_email", "unknown")
        )
        return (
            f"From: {email.get('from_email', 'unknown')}\n"
            f"To: {to}\n"
            f"CC: {cc}\n"
            f"Date: {email.get('date', 'unknown')}\n"
            f"Subject: {email.get('subject', '(no subject)')}\n"
            f"Contact: {contact_email}\n\n"
            f"{body}"
        )

    def _extract_entities(self, email: Dict, contact_email: str) -> List[str]:
        """Extract entities from email using LLM.

        Uses prompt caching: trained prompt as system (cached),
        email data as user message (varies per call).

        Args:
            email: Email dict
            contact_email: Email address of the contact

        Returns:
            List of extracted entity blobs, or empty list
        """
        logging.debug("_extract_entities called")
        try:
            prompt_template = self._get_extraction_prompt()
            if not prompt_template:
                logger.warning(
                    "Skipping extraction - no custom prompt",
                )
                return []

            email_data = self._format_email_data(
                email, contact_email,
            )

            # Try cached system prompt approach first.
            # If prompt has old-style {from_email} placeholders,
            # fall back to legacy format.
            try:
                # Test if prompt has format placeholders
                prompt_template.format(
                    from_email="", to_email="", cc_email="",
                    subject="", date="", body="",
                    contact_email="",
                )
                # Has placeholders → legacy prompt, format inline
                prompt = prompt_template.format(
                    from_email=email.get("from_email", "unknown"),
                    to_email=(
                        ", ".join(email.get("to_email", []))
                        if isinstance(email.get("to_email"), list)
                        else email.get("to_email", "unknown")
                    ),
                    cc_email=email_data.split("\n")[2][4:],
                    subject=email.get("subject", "(no subject)"),
                    date=email.get("date", "unknown"),
                    body=(
                        email.get("body_plain", "")
                        or email.get("snippet", "")
                    ),
                    contact_email=contact_email,
                )
                response = self.client.create_message_sync(
                    messages=[
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=1024,
                )
            except (KeyError, IndexError):
                # No placeholders → use as cached system prompt
                system = [
                    {
                        "type": "text",
                        "text": prompt_template,
                        "cache_control": {
                            "type": "ephemeral",
                        },
                    },
                ]
                response = self.client.create_message_sync(
                    system=system,
                    messages=[
                        {
                            "role": "user",
                            "content": (
                                "Analyze this email:\n\n"
                                + email_data
                            ),
                        },
                    ],
                    max_tokens=1024,
                )
            raw_output = response.content[0].text.strip()
            logging.debug(f"RAW OUTPUT:\n{raw_output}")
            # Check for SKIP
            if raw_output.upper() == "SKIP":
                return []

            # Split by entity delimiter
            entities = self._parse_entities(raw_output)
            return entities

        except Exception as e:
            logger.error(f"Failed to extract entities: {e}")
            # Re-raise auth errors so batch can fail-fast
            err_str = str(e).lower()
            if "401" in err_str or "authentication" in err_str:
                raise
            return []

    def _parse_entities(self, raw_output: str) -> List[str]:
        """Parse LLM output into separate entity blobs.

        Args:
            raw_output: Raw LLM output potentially containing multiple entities

        Returns:
            List of entity blob strings
        """
        # Split by the entity delimiter
        logging.debug("_parse_entities CALLED")
        ENTITY_DELIMITER = "---ENTITY---"
        entities = []
        if ENTITY_DELIMITER in raw_output:
            parts = raw_output.split(ENTITY_DELIMITER)
            logging.debug(f"Entities delimiter found: {parts}")
        elif raw_output.count("#IDENTIFIER") > 1:
            parts = [raw_output]
            logging.warning(f"More than 1 #IDENTIFIER without delimiter, skipping: {parts}")
            return entities
        else:
            # Single entity
            parts = [raw_output]
            logging.debug(f"Entities delimiter NOT found: {parts}")

        for part in parts:
            part = part.strip()
            # Validate
            if part and "#IDENTIFIERS" in part.upper():
                entities.append(part)
            else:
                logging.warning("ENTITIES NOT ADDED: empty or no #IDENTIFIER")
        return entities

    async def process_calendar_event(self, event: Dict) -> bool:
        """Process single calendar event to extract and store facts.

        Args:
            event: Event dict with id, summary, description, location, start_time, end_time, attendees

        Returns:
            True if processed successfully, False otherwise
        """
        event_id = event.get("id", "unknown")
        try:
            logger.debug(f"Processing calendar event {event_id}")

            # Extract facts from event
            facts = self._extract_calendar_facts(event)
            if not facts or facts == "No significant facts.":
                logger.debug(f"No facts extracted from event {event_id}")
                self.storage.mark_calendar_event_processed(self.owner_id, event_id)
                return True

            # Search for existing blob about this meeting/attendees
            existing = self.hybrid_search.find_for_reconsolidation(
                owner_id=self.owner_id, content=facts, namespace=self.namespace
            )

            event_desc = f"Extracted from calendar event '{event.get('summary', '')}' ({event.get('start_time', '')})"

            if existing:
                merged_content = self.llm_merge.merge(existing.content, facts)
                self.blob_storage.update_blob(
                    blob_id=existing.blob_id,
                    owner_id=self.owner_id,
                    content=merged_content,
                    event_description=event_desc,
                )
                logger.info(f"Reconsolidated blob {existing.blob_id} with event {event_id}")
            else:
                blob = self.blob_storage.store_blob(
                    owner_id=self.owner_id,
                    namespace=self.namespace,
                    content=facts,
                    event_description=event_desc,
                )
                logger.info(f"Created new blob {blob['id']} from event {event_id}")

            self.storage.mark_calendar_event_processed(self.owner_id, event_id)
            return True

        except Exception as e:
            logger.error(f"Error processing event {event_id}: {e}", exc_info=True)
            return False

    async def process_calendar_batch(self, events: List[Dict]) -> int:
        """Process batch of calendar events.

        Args:
            events: List of event dicts (from get_unprocessed_calendar_events)

        Returns:
            Number of successfully processed events
        """
        logger.info(f"Processing batch of {len(events)} calendar events")
        processed = 0

        for event in events:
            success = await self.process_calendar_event(event)
            if success:
                processed += 1

        logger.info(f"Calendar batch complete: {processed}/{len(events)} processed")
        return processed

    def _extract_calendar_facts(self, event: Dict) -> str:
        """Extract facts from calendar event using LLM.

        Args:
            event: Calendar event dict

        Returns:
            Extracted facts as natural language string
        """
        try:
            attendees = event.get("attendees", [])
            if isinstance(attendees, list):
                attendees_str = ", ".join(
                    a.get("email", "") if isinstance(a, dict) else str(a) for a in attendees
                )
            else:
                attendees_str = str(attendees)

            prompt = f"""Extract key facts about attendees from this calendar event.

TITLE: {event.get('summary', '(no title)')}
DATE/TIME: {event.get('start_time', '')} - {event.get('end_time', '')}
LOCATION: {event.get('location', '(no location)')}
ATTENDEES: {attendees_str}
DESCRIPTION: {event.get('description', '(no description)')}

---

Write a concise summary of what we learned from this meeting.
Include:
- Who attended and their relationship to the meeting
- Meeting purpose and topics discussed
- Any action items or follow-ups implied
- Context about the attendees (companies, roles if mentioned)

Output ONLY the facts as natural language prose (2-5 sentences). If no meaningful facts, output "No significant facts."
"""

            response = self.client.create_message_sync(
                messages=[{"role": "user", "content": prompt}], max_tokens=512
            )
            return response.content[0].text.strip()

        except Exception as e:
            logger.error(f"Failed to extract calendar facts: {e}")
            err_str = str(e).lower()
            if "401" in err_str or "authentication" in err_str:
                raise
            return ""

    # ==========================================
    # MRCALL PHONE CALL PROCESSING
    # ==========================================

    def _get_mrcall_extraction_prompt(self) -> Optional[str]:
        """Get MrCall extraction prompt - user-specific only.

        Returns None if no custom prompt exists (user must run /agent memory train mrcall first).

        Returns:
            The extraction prompt, or None if not configured
        """
        prompt = self.storage.get_agent_prompt(self.owner_id, "memory_mrcall")
        if prompt:
            logger.info("Using user's custom memory_mrcall prompt")
        else:
            logger.warning(
                "No MrCall prompt found - user must run /agent memory train mrcall first"
            )
        return prompt

    async def process_mrcall_conversation(self, conversation: Dict) -> bool:
        """Process single MrCall conversation to extract and store entities.

        Args:
            conversation: Conversation dict from mrcall_conversations table

        Returns:
            True if processed successfully, False otherwise
        """
        conv_id = conversation.get("id", "unknown")
        try:
            logger.info(f"Processing MrCall conversation {conv_id}")

            # Step 1: Extract entities from conversation
            entities = self._extract_mrcall_entities(conversation)
            if not entities:
                logger.debug(f"No entities extracted from conversation {conv_id}")
                self.storage.mark_mrcall_memory_processed(self.owner_id, conv_id)
                return True

            logger.debug(f"Extracted {len(entities)} entities from conversation {conv_id}")

            # Step 2: Process each entity
            contact_phone = conversation.get("contact_phone", "unknown")
            contact_name = conversation.get("contact_name", "unknown")
            call_date = conversation.get("call_started_at", "unknown")
            event_desc = (
                f"Extracted from phone call with {contact_name} ({contact_phone}) on {call_date}"
            )

            for i, entity_content in enumerate(entities):
                await self._upsert_mrcall_entity(
                    entity_content, event_desc, conv_id, i + 1, len(entities)
                )

            # Step 3: Mark as processed
            self.storage.mark_mrcall_memory_processed(self.owner_id, conv_id)
            return True

        except Exception as e:
            logger.error(f"Error processing conversation {conv_id}: {e}", exc_info=True)
            return False

    async def _upsert_mrcall_entity(
        self,
        entity_content: str,
        event_desc: str,
        conv_id: str,
        entity_num: int,
        total_entities: int,
    ) -> None:
        """Upsert a single entity blob from MrCall with reconsolidation.

        Args:
            entity_content: The entity blob content
            event_desc: Event description for the blob
            conv_id: Source conversation ID (for logging)
            entity_num: Which entity this is (1-indexed)
            total_entities: Total entities from this conversation
        """
        logger.debug(f"Upserting MrCall entity {entity_num}/{total_entities}")

        # Get top 3 candidates above threshold
        existing_blobs = self.hybrid_search.find_candidates_for_reconsolidation(
            owner_id=self.owner_id, content=entity_content, namespace=self.namespace, limit=3
        )

        upserted = False

        for existing in existing_blobs:
            logger.debug(
                f"Trying to merge with blob {existing.blob_id} (score={existing.hybrid_score:.2f})"
            )
            merged_content = self.llm_merge.merge(existing.content, entity_content)

            if "INSERT" in merged_content.upper() and len(merged_content) < 10:
                logger.debug(f"Skipping blob {existing.blob_id} - entities don't match")
                continue

            self.blob_storage.update_blob(
                blob_id=existing.blob_id,
                owner_id=self.owner_id,
                content=merged_content,
                event_description=event_desc,
            )
            logger.info(
                f"Reconsolidated blob {existing.blob_id} with conversation {conv_id} (entity {entity_num}/{total_entities})"
            )
            upserted = True
            break

        if not upserted:
            blob = self.blob_storage.store_blob(
                owner_id=self.owner_id,
                namespace=self.namespace,
                content=entity_content,
                event_description=event_desc,
            )
            logger.info(
                f"Created new blob {blob['id']} from conversation {conv_id} (entity {entity_num}/{total_entities})"
            )

    async def process_mrcall_batch(self, conversations: List[Dict]) -> int:
        """Process batch of MrCall conversations.

        Args:
            conversations: List of conversation dicts

        Returns:
            Number of successfully processed conversations
        """
        logger.info(f"Processing batch of {len(conversations)} MrCall conversations")
        processed = 0
        consecutive_failures = 0

        for conversation in conversations:
            success = await self.process_mrcall_conversation(conversation)
            if success:
                processed += 1
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    logger.error(
                        "3 consecutive failures — stopping"
                        " batch (check API key)"
                    )
                    break

        logger.info(f"MrCall batch complete: {processed}/{len(conversations)} processed")
        return processed

    # -- WhatsApp message processing -----------------------------------

    async def process_whatsapp_message(self, message: Dict) -> bool:
        """Process single WhatsApp message to extract and store entities.

        Args:
            message: Message dict from whatsapp_messages table

        Returns:
            True if processed successfully
        """
        msg_id = message.get("id", "unknown")
        try:
            text = message.get("text", "")
            if not text or len(text) < 20:
                # Skip very short messages (e.g. "ok", "si")
                self.storage.mark_whatsapp_memory_processed(self.owner_id, msg_id)
                return True

            sender = message.get("sender_name") or message.get("sender_jid", "unknown")
            is_from_me = message.get("is_from_me", False)
            timestamp = message.get("timestamp", "unknown")

            direction = "sent to" if is_from_me else "received from"
            event_desc = f"WhatsApp message {direction} {sender} on {timestamp}"

            # For WhatsApp, we create a simple entity blob per significant message
            # The LLM will merge with existing blobs for the same person
            namespace = f"PERSON:{sender}"
            content = f"WhatsApp ({timestamp}): {text}"

            # Check if blob already exists for this person
            existing_blobs = self.hybrid_search.find_candidates_for_reconsolidation(
                owner_id=self.owner_id,
                content=sender,
                namespace=namespace,
                limit=1,
            )

            if existing_blobs:
                # Merge with existing blob
                existing = existing_blobs[0]
                merged = self.llm_merge.merge(existing.content, content)

                if merged and not ("INSERT" in merged.upper() and len(merged) < 10):
                    self.blob_storage.update_blob(
                        blob_id=existing.blob_id,
                        owner_id=self.owner_id,
                        content=merged,
                        event_description=event_desc,
                    )
                else:
                    self.blob_storage.store_blob(
                        owner_id=self.owner_id,
                        namespace=namespace,
                        content=content,
                        event_description=event_desc,
                    )
            else:
                # Create new blob
                self.blob_storage.store_blob(
                    owner_id=self.owner_id,
                    namespace=namespace,
                    content=content,
                    event_description=event_desc,
                )

            self.storage.mark_whatsapp_memory_processed(self.owner_id, msg_id)
            return True

        except Exception as e:
            logger.error(f"Error processing WhatsApp message {msg_id}: {e}")
            return False

    async def process_whatsapp_batch(self, messages: List[Dict]) -> int:
        """Process batch of WhatsApp messages for memory extraction.

        Args:
            messages: List of message dicts from whatsapp_messages

        Returns:
            Number of successfully processed messages
        """
        logger.info(f"Processing batch of {len(messages)} WhatsApp messages")
        processed = 0

        for msg in messages:
            success = await self.process_whatsapp_message(msg)
            if success:
                processed += 1

        logger.info(f"WhatsApp batch complete: {processed}/{len(messages)} processed")
        return processed

    def _extract_mrcall_entities(self, conversation: Dict) -> List[str]:
        """Extract entities from MrCall conversation using LLM.

        Requires user's custom prompt (from /agent memory train mrcall).
        Returns a list of entity blobs (one per entity found).

        Args:
            conversation: Conversation dict from mrcall_conversations table

        Returns:
            List of extracted entity blobs, or empty list if no prompt configured or SKIP
        """
        try:
            # Get the extraction prompt
            prompt_template = self._get_mrcall_extraction_prompt()
            if not prompt_template:
                logger.warning("Skipping MrCall extraction - no custom prompt configured")
                return []

            # Extract conversation text from body
            conversation_text = self._extract_conversation_text(conversation.get("body"))

            # Calculate duration in readable format
            duration_ms = conversation.get("call_duration_ms", 0)
            duration_seconds = duration_ms / 1000 if duration_ms else 0
            duration_str = f"{int(duration_seconds)} seconds"

            # Format prompt with placeholders
            # Try both {{placeholder}} and {placeholder} formats
            prompt = prompt_template
            replacements = {
                "{{contact_phone}}": conversation.get("contact_phone", "unknown"),
                "{{contact_name}}": conversation.get("contact_name", "unknown"),
                "{{call_date}}": conversation.get("call_started_at", "unknown"),
                "{{call_duration}}": duration_str,
                "{{conversation}}": conversation_text,
                "{contact_phone}": conversation.get("contact_phone", "unknown"),
                "{contact_name}": conversation.get("contact_name", "unknown"),
                "{call_date}": conversation.get("call_started_at", "unknown"),
                "{call_duration}": duration_str,
                "{conversation}": conversation_text,
            }

            for placeholder, value in replacements.items():
                prompt = prompt.replace(placeholder, str(value))

            response = self.client.create_message_sync(
                messages=[{"role": "user", "content": prompt}], max_tokens=1024
            )
            raw_output = response.content[0].text.strip()
            logger.debug(f"MrCall RAW OUTPUT:\n{raw_output}")

            if raw_output.upper() == "SKIP":
                return []

            entities = self._parse_entities(raw_output)
            return entities

        except Exception as e:
            logger.error(f"Failed to extract MrCall entities: {e}")
            err_str = str(e).lower()
            if "401" in err_str or "authentication" in err_str:
                raise
            return []

    def _extract_conversation_text(self, body: any) -> str:
        """Extract conversation text from MrCall body field.

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
            # Try common field names
            for field in ["conversation", "transcript", "transcription", "messages", "text"]:
                if field in body:
                    value = body[field]
                    if isinstance(value, str):
                        return value
                    if isinstance(value, list):
                        lines = []
                        for msg in value:
                            if isinstance(msg, dict):
                                speaker = msg.get("speaker", msg.get("role", "Unknown"))
                                text = msg.get("text", msg.get("content", ""))
                                if text:
                                    lines.append(f"{speaker}: {text}")
                            elif isinstance(msg, str):
                                lines.append(msg)
                        return "\n".join(lines)

            # Stringify clean body (without audio markers)
            clean_body = {k: v for k, v in body.items() if v != "[AUDIO_STRIPPED]"}
            if clean_body:
                return str(clean_body)

        return "(Could not extract conversation)"
