"""Memory Agent - Extract facts from emails and store in entity-centric blobs.

Processes emails to extract relationship information about contacts,
storing in blobs with reconsolidation (merging with existing knowledge).

Uses hybrid search (FTS + semantic) to find existing blobs about the same entity,
then LLM-merges new information with existing knowledge.
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

from zylch.llm import LLMClient, make_llm_client
from zylch.storage import Storage
from zylch.memory import (
    BlobStorage,
    HybridSearchEngine,
    LLMMergeService,
    EmbeddingEngine,
    MemoryConfig,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Identifier parsing (Phase 1a, whatsapp-pipeline-parity)
# ---------------------------------------------------------------------
#
# The memory extraction prompt emits a structured `#IDENTIFIERS` block,
# e.g.::
#
#     #IDENTIFIERS
#     Entity type: PERSON
#     Name: Carmine Salamone
#     Email: c.salamone@cnit.it
#     Phone: +39 339 6584014, +393925358412
#
# `_parse_identifiers_block` extracts the (kind, value) tuples that we
# index into `person_identifiers` for cross-channel identity matching.
# Only structured input (the labelled lines inside the `#IDENTIFIERS`
# header) is parsed — never prose. v1 indexes email / phone / lid; names
# are excluded by design (false-merge risk on common names).

_PHONE_LABEL_RE = re.compile(
    r"^\s*[-*•]?\s*(phone|tel\.?|telefono|mobile|cellulare|cell\.?)\s*[:=]\s*(.+)$",
    re.IGNORECASE,
)
_EMAIL_LABEL_RE = re.compile(
    r"^\s*[-*•]?\s*email\s*[:=]\s*(.+)$",
    re.IGNORECASE,
)
_LID_LABEL_RE = re.compile(
    r"^\s*[-*•]?\s*lid\s*[:=]\s*(.+)$",
    re.IGNORECASE,
)


def _normalise_phone(raw: str) -> Optional[str]:
    """Canonicalise a phone string for indexing.

    Strips spaces / dots / dashes / parentheses, preserves a leading '+'
    when present (or upgrades a leading '00' to '+'). Returns None for
    inputs that produce <8 digits — they're either placeholders ("none",
    "unknown") or noise.

    Defense-in-depth (whatsapp-pipeline-parity Phase 2c): inputs
    containing ``@`` are rejected outright. The legacy email-only memory
    prompt sometimes mislabels a WhatsApp ``<digits>@lid`` pseudonym as
    ``Phone: <digits>@lid``; without this guard the digit-strip would
    happily index the LID's numeric local-part as a phone, polluting
    the cross-channel index with bogus matches.
    """
    if not raw:
        return None
    if "@" in raw:
        # LID-shaped or email-shaped value labelled as a phone — refuse.
        return None
    s = raw.strip()
    # Remove embedded narrative tails like "+39 339 6584014 (cell)"
    # by clipping at the first character that is neither a digit, +,
    # whitespace, dot, dash, parenthesis, or slash.
    cleaned = []
    for ch in s:
        if ch.isdigit() or ch in "+- .()/":
            cleaned.append(ch)
        else:
            break
    s = "".join(cleaned).strip()
    if not s:
        return None
    has_plus = s.startswith("+") or s.startswith("00")
    digits = re.sub(r"\D+", "", s)
    if has_plus and digits.startswith("00"):
        digits = digits[2:]
    if len(digits) < 8:
        return None
    return ("+" + digits) if has_plus else digits


def _parse_identifiers_block(entity_content: str) -> List[Tuple[str, str]]:
    """Parse the `#IDENTIFIERS` block of a blob into (kind, value) tuples.

    Returns kinds in {'email', 'phone', 'lid'}. Multi-value lines (e.g.
    ``Phone: +39 339 ..., +39 392 ...``) split on commas. Returns an
    empty list when the block is missing — callers fall back to no-op
    (a blob without structured identifiers cannot be cross-channel
    matched in v1; the cosine fallback in `_upsert_entity` still runs).
    """
    if not entity_content:
        return []
    lines = entity_content.splitlines()
    in_block = False
    out: List[Tuple[str, str]] = []
    for raw in lines:
        s = raw.strip()
        if s.startswith("#IDENTIFIERS"):
            in_block = True
            continue
        if in_block and s.startswith("#"):
            break
        if not in_block or not s:
            continue
        if s.startswith("**") or s.lower().startswith("reminder:"):
            continue

        m = _EMAIL_LABEL_RE.match(s)
        if m:
            for piece in m.group(1).split(","):
                v = piece.strip().strip("<>").lower()
                # Defensive: an email must contain '@' and at least one '.'
                # in the domain; placeholders like "(none)" / "unknown" fail.
                if "@" in v and "." in v.split("@", 1)[-1]:
                    out.append(("email", v))
            continue

        m = _PHONE_LABEL_RE.match(s)
        if m:
            for piece in m.group(2).split(","):
                p = piece.strip()
                # Recovery path: the legacy email-only prompt sometimes
                # writes a WhatsApp LID into the Phone: field. Reroute
                # anything that looks like a JID (contains '@lid') to
                # the LID kind so cross-channel match still gets the
                # signal.
                if "@lid" in p.lower():
                    out.append(("lid", p.lower()))
                    continue
                norm = _normalise_phone(p)
                if norm:
                    out.append(("phone", norm))
            continue

        m = _LID_LABEL_RE.match(s)
        if m:
            for piece in m.group(1).split(","):
                v = piece.strip().lower()
                if v and "@lid" in v:
                    out.append(("lid", v))
                elif v.isdigit() and len(v) >= 6:
                    out.append(("lid", v))
            continue

    # Stable de-dup preserving order
    seen = set()
    deduped: List[Tuple[str, str]] = []
    for k, v in out:
        if (k, v) in seen:
            continue
        seen.add((k, v))
        deduped.append((k, v))
    return deduped


def _extract_identifier_query(entity_content: str) -> Optional[str]:
    """Pull the #IDENTIFIERS block as a focused search query.

    The memory extraction prompt mandates a structured block::

        #IDENTIFIERS
        Entity type: person
        Name: Carmine Salamone
        Email: c.salamone@cnit.it
        Phone: ...

    These literals are the same across emails about the same entity,
    while #ABOUT/#HISTORY paragraphs vary. Searching against just
    these lines gives a reliable >0.65 cosine match between two
    records of the same person.

    Returns ``None`` when the block is missing/unrecognised so the
    caller can fall back to the full content (legacy or malformed
    extraction).
    """
    if not entity_content:
        return None
    lines = entity_content.splitlines()
    in_identifiers = False
    out: List[str] = []
    for raw in lines:
        s = raw.strip()
        if s.startswith("#IDENTIFIERS"):
            in_identifiers = True
            continue
        # Any other top-level section ends the identifiers block.
        if in_identifiers and s.startswith("#"):
            break
        if not in_identifiers or not s:
            continue
        # The merge prompt sometimes injects "**REMEMBER** ..." reminders
        # mid-block — drop them, they're for the LLM not for indexing.
        if s.startswith("**") or s.lower().startswith("reminder:"):
            continue
        out.append(s)
    if not out:
        return None
    return " ".join(out).strip() or None


class MemoryWorker:
    """Worker for extracting facts from emails and storing in entity-centric blobs.

    Flow:
    1. Extract facts from email about the contact
    2. Search for existing blob about this entity (hybrid search)
    3. If found: LLM-merge new facts with existing knowledge
    4. If not found: create new blob
    5. Mark email as processed
    """

    def __init__(self, storage: Storage, owner_id: str):
        """Initialize MemoryWorker.

        Args:
            storage: Storage instance
            owner_id: Owner ID for namespace
        """
        self.storage = storage
        self.owner_id = owner_id
        self.namespace = f"user:{owner_id}"

        # Initialize components
        config = MemoryConfig()
        self.embedding_engine = EmbeddingEngine(config)
        from zylch.storage.database import get_session

        self.blob_storage = BlobStorage(get_session, self.embedding_engine)
        self.hybrid_search = HybridSearchEngine(get_session, self.embedding_engine)
        self.llm_merge = LLMMergeService()

        # LLM client for fact extraction. Raises RuntimeError if no
        # transport is configured — surfaces "no LLM" as a clear error
        # rather than silently producing no memories.
        self.client: LLMClient = make_llm_client()

        # Cache for user's custom prompt (lazy loaded)
        self._custom_prompt: Optional[str] = None
        self._custom_prompt_loaded: bool = False

        logger.info(f"MemoryWorker initialized for namespace={self.namespace}")

    def _get_extraction_prompt(self) -> Optional[str]:
        """Get extraction prompt - user-specific only.

        Loads user's custom prompt from DB on first call, caches for
        subsequent calls. Returns None if no custom prompt exists
        (user must train it via /agent train memory or via the
        process pipeline's auto-train).

        Reads ``memory_message`` first (the channel-aware key, since
        whatsapp-pipeline-parity Phase 2b on 2026-05-08), falls back
        to the legacy ``memory_email`` key for installs that haven't
        retrained since the rename — these are still email-only
        compatible because the legacy prompt's #IDENTIFIERS section
        was already structured.

        Returns:
            The extraction prompt, or None if not configured.
        """
        if not self._custom_prompt_loaded:
            raw = self.storage.get_agent_prompt(self.owner_id, "memory_message")
            source_key = "memory_message"
            if not (raw and raw.strip()):
                raw = self.storage.get_agent_prompt(self.owner_id, "memory_email")
                source_key = "memory_email"
            # Treat empty string as None
            self._custom_prompt = raw if raw and raw.strip() else None
            self._custom_prompt_loaded = True

            if self._custom_prompt:
                logger.info(f"Using user's custom {source_key} prompt")
            else:
                logger.debug("No custom prompt found — will auto-train")

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
        source_kind: str = "email",
    ) -> None:
        """Upsert a single entity blob with reconsolidation.

        Match strategy (Phase 1b, whatsapp-pipeline-parity, 2026-05-07):
        identifier-first, cosine fallback. Candidates are tried in this
        order:

          1. Blobs returned by ``find_blobs_by_identifiers`` — exact
             match on the new entity's email / phone / lid identifiers
             against the ``person_identifiers`` index. Catches the
             "8 distinct Carmine Salamone PERSON blobs" case where two
             records of the same person share `Email: c.salamone@cnit.it`
             but their #ABOUT / #HISTORY paragraphs have drifted enough
             that the cosine score on the full block dropped below the
             0.65 reconsolidation threshold.

          2. Blobs returned by the legacy cosine-on-`#IDENTIFIERS`
             search — fallback for blobs that pre-date the identifier
             index OR for entities whose `#IDENTIFIERS` block has no
             email/phone/lid (anonymised contacts, name-only entities).

        The LLM merge gate is unchanged: every candidate is shown to
        the merge model, which returns "INSERT" when the entities don't
        in fact match. So a stale identifier (e.g. a shared company
        switchboard number that ends up in two distinct PERSON blobs)
        cannot force an incorrect merge.

        Bug G (2026-05-06) baseline still applies: when the cosine
        fallback runs, the search query is the structured #IDENTIFIERS
        block, not the full content.

        Args:
            entity_content: The entity blob content
            event_desc: Event description for the blob
            email_id: Source email ID (for logging)
            entity_num: Which entity this is (1-indexed)
            total_entities: Total entities from this email
        """
        logger.info(f"Upserting entity, searching with:\n{entity_content}\n\n")

        # Parse identifiers ONCE: used for the new identifier-first
        # match (below) AND for writing rows into person_identifiers
        # after the upsert (Phase 1a).
        identifiers = _parse_identifiers_block(entity_content)

        # Phase 1b — identifier-first lookup.
        # Returns blob ids that share at least one (kind, value) tuple
        # with the new entity. Empty when the new entity has no
        # email/phone/lid identifiers OR when none of its identifiers
        # is in the index.
        id_matched_blob_ids: List[str] = []
        if identifiers:
            try:
                id_matched_blob_ids = self.storage.find_blobs_by_identifiers(
                    owner_id=self.owner_id,
                    identifiers=identifiers,
                )
            except Exception as e:
                logger.warning(f"[memory] find_blobs_by_identifiers failed: {e}")
                id_matched_blob_ids = []
            if id_matched_blob_ids:
                logger.info(
                    f"[memory] identifier match: {len(id_matched_blob_ids)} blob(s) "
                    f"on kinds={[k for k, _ in identifiers]} "
                    f"hits={id_matched_blob_ids}"
                )

        # Identifier-based search query (Bug G fix). Falls back to the
        # full content when the LLM didn't produce a parseable
        # IDENTIFIERS block (legacy / malformed extraction).
        query = _extract_identifier_query(entity_content) or entity_content
        if query is not entity_content:
            logger.debug(f"[memory] using identifier-query for reconsolidation lookup: {query!r}")

        # Diagnostic: log top-3 candidates with their scores BEFORE
        # the threshold filter, so investigation of "why didn't it
        # merge?" doesn't require re-running the search by hand. Pulls
        # the same alpha=0.5 hybrid_search the threshold method uses.
        debug_results = self.hybrid_search.search(
            owner_id=self.owner_id,
            query=query,
            namespace=self.namespace,
            limit=3,
            alpha=0.5,
        )
        if debug_results:
            for i, r in enumerate(debug_results, 1):
                first_id_line = ""
                for line in (r.content or "").splitlines():
                    if line.strip().lower().startswith("name:"):
                        first_id_line = line.strip()
                        break
                logger.info(
                    f"[memory] reconsolidation candidate {i}/{len(debug_results)}: "
                    f"blob_id={r.blob_id} hybrid={r.hybrid_score:.3f} "
                    f"identifier={first_id_line!r}"
                )
        else:
            logger.info(
                f"[memory] reconsolidation candidate search returned 0 results "
                f"for query={query!r}"
            )

        # Threshold-gated cosine candidates (existing path).
        cosine_candidates = self.hybrid_search.find_candidates_for_reconsolidation(
            owner_id=self.owner_id, content=query, namespace=self.namespace, limit=3
        )

        # Compose the merge-candidate list: identifier-matched first
        # (priority), then cosine-matched not already in the identifier
        # set. Each entry is a (blob_id, content, source) triple where
        # `source` is just for logging — the LLM-merge gate is shared.
        cosine_blob_ids = {str(c.blob_id) for c in cosine_candidates}
        merge_candidates: List[Dict[str, str]] = []
        seen_ids = set()

        for bid in id_matched_blob_ids:
            if bid in seen_ids:
                continue
            blob_dict = self.blob_storage.get_blob(bid, self.owner_id)
            if not blob_dict or not blob_dict.get("content"):
                # Stale identifier row (blob was deleted or moved owner).
                # Skip silently — the LLM can't merge with a missing blob.
                continue
            seen_ids.add(bid)
            merge_candidates.append(
                {
                    "blob_id": bid,
                    "content": blob_dict["content"],
                    "source": (
                        "identifier+cosine" if bid in cosine_blob_ids else "identifier-only"
                    ),
                }
            )

        for cand in cosine_candidates:
            bid = str(cand.blob_id)
            if bid in seen_ids:
                continue
            seen_ids.add(bid)
            merge_candidates.append(
                {
                    "blob_id": bid,
                    "content": cand.content,
                    "source": f"cosine={cand.hybrid_score:.3f}",
                }
            )

        upserted = False
        # Track which blob this email contributed to. Either an
        # existing one (merge) or a freshly created one (no match).
        # Written to email_blobs at the end so the F7 task worker can
        # later look up "blobs from this email" without similarity
        # search (Fase 3.1).
        linked_blob_id: Optional[str] = None

        for cand in merge_candidates:
            bid = cand["blob_id"]
            existing_content = cand["content"]
            source = cand["source"]
            logger.debug(f"[memory] merge attempt blob_id={bid} source={source}")
            merged_content = self.llm_merge.merge(existing_content, entity_content)

            # If LLM says INSERT (entities don't match), try next candidate
            if "INSERT" in merged_content.upper() and len(merged_content) < 10:
                logger.debug(f"[memory] LLM merge rejected blob_id={bid} source={source}")
                continue

            # Successful merge
            self.blob_storage.update_blob(
                blob_id=bid,
                owner_id=self.owner_id,
                content=merged_content,
                event_description=event_desc,
            )
            logger.info(
                f"Reconsolidated blob {bid} with email {email_id} "
                f"(entity {entity_num}/{total_entities}, source={source})"
            )
            linked_blob_id = bid
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
            linked_blob_id = str(blob["id"])

        # Write the channel-specific (source_id, blob_id) join row.
        # Idempotent — a re-run on the same source is a no-op. Failures
        # are logged but never raise: the blob already exists, the
        # index is a denorm hint and not load-bearing.
        # `source_kind` controls which join table receives the row:
        # `"email"` → email_blobs (Fase 3.1, default for backward compat),
        # `"whatsapp"` → whatsapp_blobs (Phase 2c, whatsapp-pipeline-parity).
        if linked_blob_id and email_id:
            try:
                if source_kind == "whatsapp":
                    self.storage.add_whatsapp_blob_link(
                        owner_id=self.owner_id,
                        whatsapp_message_id=email_id,
                        blob_id=linked_blob_id,
                    )
                else:
                    self.storage.add_email_blob_link(
                        owner_id=self.owner_id,
                        email_id=email_id,
                        blob_id=linked_blob_id,
                    )
            except Exception as e:
                logger.warning(
                    f"[memory] add_{source_kind}_blob_link({email_id}, {linked_blob_id}) failed: {e}"
                )

        # Write person_identifiers rows (whatsapp-pipeline-parity, Phase 1a).
        # The `identifiers` list was already parsed at the top of this
        # method for the identifier-first lookup (Phase 1b); reuse it
        # here so we parse the block exactly once per upsert. The merge
        # case is load-bearing: when an existing blob's content gets
        # richer because we just merged a new email that exposed the
        # contact's phone for the first time, this picks up those new
        # identifiers without requiring the blob to be re-extracted.
        if linked_blob_id and identifiers:
            try:
                inserted = self.storage.add_person_identifiers(
                    owner_id=self.owner_id,
                    blob_id=linked_blob_id,
                    identifiers=identifiers,
                )
                if inserted:
                    logger.debug(
                        f"[memory] add_person_identifiers blob={linked_blob_id} "
                        f"new_rows={inserted} kinds="
                        f"{[k for k, _ in identifiers]}"
                    )
            except Exception as e:
                logger.warning(f"[memory] add_person_identifiers({linked_blob_id}) failed: {e}")

    async def process_batch(
        self,
        emails: List[Dict],
        concurrency: int = 5,
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
            f"Processing batch of {len(emails)} emails" f" (concurrency={concurrency})",
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
                            "3 consecutive failures — stopping" " batch (check API key)",
                        )
                        stop = True

        await asyncio.gather(
            *[_process_one(e) for e in emails],
            return_exceptions=True,
        )
        logger.info(
            f"Batch complete:" f" {processed}/{len(emails)} processed",
        )
        return processed

    def _format_email_data(
        self,
        email: Dict,
        contact_email: str,
    ) -> str:
        """Format email fields as plain text for LLM."""
        body = email.get("body_plain", "") or email.get("snippet", "")
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
                email,
                contact_email,
            )

            # Try cached system prompt approach first.
            # If prompt has old-style {from_email} placeholders,
            # fall back to legacy format.
            try:
                # Test if prompt has format placeholders
                prompt_template.format(
                    from_email="",
                    to_email="",
                    cc_email="",
                    subject="",
                    date="",
                    body="",
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
                    body=(email.get("body_plain", "") or email.get("snippet", "")),
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
                            "content": ("Analyze this email:\n\n" + email_data),
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

    # =========================================================
    # WhatsApp message processing (whatsapp-pipeline-parity Phase 2c)
    # =========================================================

    # Skip messages shorter than this — single emoji, "ok", "ciao" — that
    # carry no extractable identity / context. Same threshold the deleted
    # 2026-04 skeleton used; we still mark them as processed so we don't
    # re-evaluate every Update.
    _WA_MIN_TEXT_LEN = 20

    async def process_whatsapp_message(self, message: Dict) -> bool:
        """Process one WhatsApp message: extract entities, upsert blobs,
        write whatsapp_blobs link, mark processed.

        Mirror of ``process_email``. The per-message LLM prompt is the
        same channel-aware ``memory_message`` prompt the email path uses
        (Phase 2b); only the envelope shape passed as the user message
        differs.

        v1: 1-on-1 messages only (the storage helper already filters
        ``is_group=False``).
        """
        wa_id = message.get("id", "unknown")
        try:
            text = (message.get("text") or "").strip()
            if len(text) < self._WA_MIN_TEXT_LEN:
                logger.debug(
                    f"[memory] WA {wa_id} skipped — text too short "
                    f"(len={len(text)} < {self._WA_MIN_TEXT_LEN})"
                )
                self.storage.mark_whatsapp_memory_processed(self.owner_id, wa_id)
                return True

            entities = self._extract_entities_for_message(
                envelope=self._format_whatsapp_data(message),
                channel_label="WhatsApp",
            )
            if not entities:
                logger.debug(f"[memory] WA {wa_id} produced 0 entities — marking processed")
                self.storage.mark_whatsapp_memory_processed(self.owner_id, wa_id)
                return True

            ts = message.get("timestamp", "unknown")
            sender_label = (
                message.get("sender_name")
                or message.get("sender_jid")
                or "unknown"
            )
            event_desc = f"Extracted from WhatsApp message {wa_id} ({ts}) from {sender_label}"

            for i, entity_content in enumerate(entities):
                await self._upsert_entity(
                    entity_content=entity_content,
                    event_desc=event_desc,
                    email_id=wa_id,
                    entity_num=i + 1,
                    total_entities=len(entities),
                    source_kind="whatsapp",
                )

            self.storage.mark_whatsapp_memory_processed(self.owner_id, wa_id)
            return True

        except Exception as e:
            logger.error(f"Error processing WhatsApp message {wa_id}: {e}", exc_info=True)
            return False

    async def process_whatsapp_batch(
        self,
        messages: List[Dict],
        concurrency: int = 5,
    ) -> int:
        """Process a batch of WhatsApp messages with bounded concurrency.

        Same shape as ``process_batch`` for emails: 3 consecutive failures
        abort the batch (the failing API key / quota will not recover
        within a few hundred ms, hammering it just spreads the error).
        """
        import asyncio

        if not messages:
            return 0
        logger.info(
            f"Processing batch of {len(messages)} WA messages (concurrency={concurrency})"
        )
        sem = asyncio.Semaphore(concurrency)
        processed = 0
        failures = 0
        stop = False

        async def _process_one(msg: Dict):
            nonlocal processed, failures, stop
            if stop:
                return
            async with sem:
                if stop:
                    return
                ok = await self.process_whatsapp_message(msg)
                if ok:
                    processed += 1
                    failures = 0
                else:
                    failures += 1
                    if failures >= 3:
                        logger.error(
                            "3 consecutive WA failures — stopping batch (check API key)"
                        )
                        stop = True

        await asyncio.gather(
            *[_process_one(m) for m in messages],
            return_exceptions=True,
        )
        logger.info(f"WA batch complete: {processed}/{len(messages)} processed")
        return processed

    def _format_whatsapp_data(self, message: Dict) -> str:
        """Render a WhatsApp message as the channel-aware envelope the
        Phase 2b memory_message prompt expects.

        Mirror of ``_format_email_data`` in shape — envelope first, then
        a blank line, then the body — so the cached-system extraction
        path can hand it straight to the LLM as a user message.

        LID resolution: when the sender_jid is a privacy-mode
        ``<digits>@lid``, look up the contact in ``whatsapp_contacts``
        (populated locally by ``WhatsAppSyncService.sync_lid_contacts``
        from neonize's ``whatsmeow_lid_map``). If a real phone is
        resolved, the envelope carries BOTH ``Phone:`` and ``LID:`` so
        the LLM-generated #IDENTIFIERS can drive cross-channel match
        against email-derived blobs that share the same phone.
        """
        sender_jid = message.get("sender_jid") or ""
        sender_name = message.get("sender_name") or ""
        ts = message.get("timestamp") or "unknown"
        text = message.get("text") or ""

        # Resolve the sender phone for the From line. WA stores the JID
        # canonicalised: digits + '@s.whatsapp.net' for real phone numbers,
        # digits + '@lid' for privacy-mode pseudonyms.
        phone = ""
        lid = ""
        if "@s.whatsapp.net" in sender_jid:
            digits = sender_jid.split("@", 1)[0]
            if digits:
                phone = "+" + digits
        elif "@lid" in sender_jid:
            lid = sender_jid
            # Resolve LID → real phone via whatsapp_contacts. Critical
            # for cross-channel identity: an email blob about Carmine
            # carries Phone: +393395... and a WhatsApp message from
            # Carmine arrives with sender_jid=<lid>@lid. Without this
            # lookup the WA blob can't match the email blob.
            try:
                contact = self.storage.get_whatsapp_contact_by_jid(self.owner_id, sender_jid)
            except Exception as e:
                logger.warning(f"[memory] LID resolve failed for {sender_jid}: {e}")
                contact = None
            if contact:
                resolved = (contact.get("phone_number") or "").strip()
                if resolved.startswith("+"):
                    phone = resolved
                if not sender_name:
                    sender_name = (
                        contact.get("name")
                        or contact.get("push_name")
                        or sender_name
                    )

        # Build the From line: prefer "<Name> (<phone>)" when both are
        # present. Drop the phone when only the LID is known — emitting
        # `+<lid>` would confuse the LLM into producing a bogus Phone:
        # in #IDENTIFIERS.
        if sender_name and phone:
            from_line = f"From: {sender_name} ({phone})"
        elif sender_name:
            from_line = f"From: {sender_name}"
        elif phone:
            from_line = f"From: {phone}"
        elif lid:
            from_line = f"From: {lid}"
        else:
            from_line = "From: unknown"

        # Contact line: stable identifier the worker uses internally,
        # mirrors the email path's `Contact: <email>`. Prefer the phone
        # when known, fall back to the LID.
        contact_value = phone or lid or sender_name or "unknown"

        envelope = (
            "Channel: WhatsApp\n"
            f"{from_line}\n"
            f"At: {ts}\n"
            "Group: (1-on-1)\n"
            f"Contact: {contact_value}\n"
        )
        # Explicit Phone/LID lines below the From hint help the LLM emit
        # them in #IDENTIFIERS without inferring from prose. Both are
        # emitted when both are known — the email-side identifier index
        # keys on Phone, the future MrCall integration may key on LID.
        if phone:
            envelope += f"Phone: {phone}\n"
        if lid:
            envelope += f"LID: {lid}\n"

        return envelope + "\n" + text

    def _extract_entities_for_message(
        self,
        envelope: str,
        channel_label: str,
    ) -> List[str]:
        """Run the cached-system memory_message prompt on a generic
        message envelope (channel-agnostic). Returns the parsed entity
        blobs; empty list when the LLM returns SKIP / fails / has no
        prompt configured.

        This is the channel-aware sibling of ``_extract_entities``; the
        latter still owns the legacy email-only ``.format()`` placeholder
        path for prompts that pre-date Phase 2b.
        """
        try:
            prompt_template = self._get_extraction_prompt()
            if not prompt_template:
                logger.warning(f"Skipping {channel_label} extraction — no custom prompt")
                return []

            system = [
                {
                    "type": "text",
                    "text": prompt_template,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
            user_text = f"Analyze this message:\n\n{envelope}"
            response = self.client.create_message_sync(
                system=system,
                messages=[{"role": "user", "content": user_text}],
                max_tokens=1024,
            )
            raw_output = response.content[0].text.strip()
            if raw_output.upper() == "SKIP":
                return []
            return self._parse_entities(raw_output)
        except Exception as e:
            logger.error(f"Failed to extract entities ({channel_label}): {e}")
            err_str = str(e).lower()
            if "401" in err_str or "authentication" in err_str:
                raise
            return []

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

            linked_blob_id: Optional[str] = None
            if existing:
                merged_content = self.llm_merge.merge(existing.content, facts)
                self.blob_storage.update_blob(
                    blob_id=existing.blob_id,
                    owner_id=self.owner_id,
                    content=merged_content,
                    event_description=event_desc,
                )
                logger.info(f"Reconsolidated blob {existing.blob_id} with event {event_id}")
                linked_blob_id = str(existing.blob_id)
            else:
                blob = self.blob_storage.store_blob(
                    owner_id=self.owner_id,
                    namespace=self.namespace,
                    content=facts,
                    event_description=event_desc,
                )
                logger.info(f"Created new blob {blob['id']} from event {event_id}")
                linked_blob_id = str(blob["id"])

            # Fase 3.1: same association table pattern as email_blobs.
            if linked_blob_id and event_id:
                try:
                    self.storage.add_calendar_blob_link(
                        owner_id=self.owner_id,
                        event_id=event_id,
                        blob_id=linked_blob_id,
                    )
                except Exception as e:
                    logger.warning(
                        f"[memory] add_calendar_blob_link({event_id}, {linked_blob_id}) failed: {e}"
                    )

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

        Same identifier-query treatment as ``_upsert_entity`` (Bug G):
        the structured #IDENTIFIERS block is the stable signal across
        records of the same caller.

        Args:
            entity_content: The entity blob content
            event_desc: Event description for the blob
            conv_id: Source conversation ID (for logging)
            entity_num: Which entity this is (1-indexed)
            total_entities: Total entities from this conversation
        """
        logger.debug(f"Upserting MrCall entity {entity_num}/{total_entities}")

        query = _extract_identifier_query(entity_content) or entity_content

        # Get top 3 candidates above threshold
        existing_blobs = self.hybrid_search.find_candidates_for_reconsolidation(
            owner_id=self.owner_id, content=query, namespace=self.namespace, limit=3
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
                    logger.error("3 consecutive failures — stopping" " batch (check API key)")
                    break

        logger.info(f"MrCall batch complete: {processed}/{len(conversations)} processed")
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
