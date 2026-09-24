"""Memory worker: collect each channel's sources and hand them to the harness.

The worker owns what only it can know — how to fetch a mail, a WhatsApp
message, a calendar event or a MrCall conversation, how to render it, and the
owner's trained extraction prompts. Everything that decides meaning is behind
``zylch.memory.mnemonic.ingestion.ingest``: when extraction is paid and how it
is bounded and persisted, which candidates the mnemonic role is shown, what
each extracted entity's subject is, and what is written — through the
retaining rewrite, in one company transaction, with one replay contract per
source. The worker marks a source processed only when that answer says every
child is terminal.
"""

from zylch.services.preparation import bounded_item, bounded_operation

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from zylch.memory.response_validation import complete_memory_text
from zylch.llm import LLMClient, make_llm_client, routed_model
from zylch.llm.budget import BudgetError
from zylch.llm.usage import call_site
from zylch.storage import Storage
from zylch.memory import (
    BlobStorage,
    HybridSearchEngine,
    LLMMergeService,
    EmbeddingEngine,
    MemoryConfig,
)

logger = logging.getLogger(__name__)


def _harness():
    """The harness surfaces, imported at call time.

    The mnemonic package imports this module's identifier parser, so a
    module-level import here would be a cycle; ``wiring.parse_identifiers_block``
    defers for the same reason from the other side.
    """
    from zylch.memory.mnemonic.ingestion import Source, ingest
    from zylch.memory.mnemonic.wiring import CommitContext

    return Source, ingest, CommitContext

# Measured email extraction needs room for complete multi-entity output.
# Admission reserves this ceiling; billing still follows actual token usage.
EMAIL_EXTRACTION_MAX_TOKENS = 4096


# ---------------------------------------------------------------------
# Identifier parsing (Phase 1a, whatsapp-pipeline-parity)
# ---------------------------------------------------------------------
#
# The memory extraction prompt emits a structured `#IDENTIFIERS` block,
# e.g.::
#
#     #IDENTIFIERS
#     Entity type: PERSON
#     Name: John Smith
#     Email: contact@example.com
#     Phone: +39 333 1234567, +393331234567
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
    # Remove embedded narrative tails like "+39 333 1234567 (cell)"
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


def _entity_type(entity_content: str) -> str:
    """Return the upper-cased ``Entity type:`` value, or ''."""
    for line in (entity_content or "").splitlines():
        if line.strip().lower().startswith("entity type:"):
            return line.split(":", 1)[1].strip().upper()
    return ""


def _parse_identifiers_block(entity_content: str) -> List[Tuple[str, str]]:
    """Parse the `#IDENTIFIERS` block of a blob into (kind, value) tuples.

    Returns kinds in {'email', 'phone', 'lid'}. Multi-value lines (e.g.
    ``Phone: +39 339 ..., +39 392 ...``) split on commas. Returns an
    empty list when the block is missing — callers fall back to no-op
    (a blob without structured identifiers cannot be cross-channel
    matched in v1; the harness's cosine candidates still run).
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


def _shared_self_notion() -> Optional[str]:
    """The company store's self-notion, or None when unset/unavailable."""
    try:
        from zylch.memory.store import get_meta
        from zylch.storage.database import current_memory_engine

        engine = current_memory_engine()
        if engine is None:
            return None
        return get_meta(engine).get("self_notion") or None
    except Exception as e:
        logger.debug(f"[memory] self-notion unavailable: {e}")
        return None


def _extract_identifier_query(entity_content: str) -> Optional[str]:
    """Pull the #IDENTIFIERS block as a focused search query.

    The memory extraction prompt mandates a structured block::

        #IDENTIFIERS
        Entity type: person
        Name: John Smith
        Email: contact@example.com
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
    """Collects each channel's sources and takes them through the harness.

    Flow, for every channel:
    1. Fetch the source and render it (envelope and body, or the call's text)
    2. Hand the rendered text, the admitted stage and the extraction closure to
       ``ingestion.ingest``, which pays for extraction under the source's own
       grant, persists the manifest and decides every extracted entity through
       the mnemonic role and the retaining commit
    3. Mark the source processed only when the answer says every child is
       terminal — committed, or deliberately skipped
    """

    @property
    def namespace(self) -> str:
        """The company's entity namespace, resolved at use — not at construction.

        Entities are company knowledge: the namespace is the company's and
        ``owner_id`` is written on every row as provenance only. Lazy so a
        worker built before the key exists (tests, tooling) does not fail,
        and so a rebind to another company at runtime is followed.
        """
        override = getattr(self, "_namespace_override", None)
        if override:
            return override
        from zylch.memory.company_key import entity_namespace, require_company_key

        return entity_namespace(require_company_key())

    @namespace.setter
    def namespace(self, value: str) -> None:
        """Pin the namespace explicitly (tests, tooling); ``None`` restores the lazy default."""
        self._namespace_override = value or None

    def __init__(self, storage: Storage, owner_id: str):
        """Initialize MemoryWorker.

        Args:
            storage: Storage instance
            owner_id: Owner ID for namespace
        """
        self.storage = storage
        self.owner_id = owner_id

        # Initialize components
        config = MemoryConfig()
        self.embedding_engine = EmbeddingEngine(config)
        from zylch.storage.database import get_session

        self.blob_storage = BlobStorage(get_session, self.embedding_engine)
        self.hybrid_search = HybridSearchEngine(get_session, self.embedding_engine)
        # MODEL_MEMORY_MERGE per-worker knob (empty → engine default). The
        # merge service itself is kept for the merge-gate canary the pipeline
        # runs; the worker's own writes no longer call it.
        self.llm_merge = LLMMergeService(model=routed_model("MODEL_MEMORY_MERGE"))

        # LLM client for fact extraction. Raises RuntimeError if no
        # transport is configured — surfaces "no LLM" as a clear error
        # rather than silently producing no memories. MODEL_MEMORY_EXTRACT
        # per-worker knob (empty → engine default).
        self.client: LLMClient = make_llm_client(model=routed_model("MODEL_MEMORY_EXTRACT"))
        # The client the mnemonic role decides each extracted entity with,
        # routed by the same knob the merge used to be: deciding what an
        # entity becomes is the merge, so the per-worker choice keeps meaning.
        self.decision_client: LLMClient = make_llm_client(model=routed_model("MODEL_MEMORY_MERGE"))

        # Cache for user's custom prompt (lazy loaded)
        self._custom_prompt: Optional[str] = None
        self._custom_prompt_loaded: bool = False

        # Merge-gate guard. When the build pipeline's merge_gate_selfcheck
        # finds the gate broken-open (the model merges unrelated entities
        # instead of refusing — the 2026-06 universal-"John"-sink
        # regression), it flips this to False and the mnemonic role is shown
        # no candidate for any entity, so it can only create or skip: every
        # entity becomes a fresh blob, exactly as before. Duplicates are
        # recoverable via the reconsolidate sweep; a silent universal merge
        # is not. A FACT's exact-row pin survives the brake: it is mechanical
        # dedup, not the merge model's judgment.
        self.merge_enabled: bool = True

        logger.info(f"MemoryWorker initialized for owner={owner_id}")

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

            # One company self-notion, injected for EVERY profile sharing
            # the store, whatever its own trainer inferred: the extractor
            # must refuse to store facts about the company it works for,
            # and two profiles disagreeing about who that is would make one
            # of them write the company into shared memory permanently.
            if self._custom_prompt:
                notion = _shared_self_notion()
                if notion:
                    self._custom_prompt += (
                        "\n\n**COMPANY SELF-NOTION (shared by every account of this company; "
                        "it overrides whatever USER_COMPANY this prompt inferred above)**\n"
                        f"USER_COMPANY: {notion}\n"
                        "DO NOT create or update a COMPANY entity describing this company, "
                        "and DO NOT extract its people as external contacts.\n"
                    )

            if self._custom_prompt:
                from zylch.memory.extraction_format import SERIALIZATION_CONTRACT

                self._custom_prompt += SERIALIZATION_CONTRACT
                logger.info(f"Using user's custom {source_key} prompt")
            else:
                logger.debug("No custom prompt found — will auto-train")

        return self._custom_prompt

    def has_custom_prompt(self) -> bool:
        """Check if user has a custom extraction prompt."""
        if not self._custom_prompt_loaded:
            self._get_extraction_prompt()
        return self._custom_prompt is not None

    @bounded_item("memory:email")
    async def process_email(self, email: Dict) -> bool:
        """Take one mail through the harness; mark it processed only when it is settled.

        Each mail may contain several entities. Extraction, candidate
        selection, the semantic decision and the write happen behind
        ``ingestion.ingest``; the mail's ``memory_processed_at`` moves only
        when every extracted entity is committed or deliberately skipped.

        Args:
            email: Email dict with id, from_email, to_email, subject, body_plain, date

        Returns:
            True if the source is settled, False otherwise
        """
        email_id = email.get("id", "unknown")
        # Memory unavailable (no key, an unknown typed key, no store): the
        # extraction would spend an LLM call and then have nowhere to write,
        # every tick, for every unprocessed mail. Leave the mail unprocessed
        # — it is retried once memory is back — and spend nothing.
        from zylch.storage.database import memory_unavailable_reason

        reason = memory_unavailable_reason()
        if reason:
            logger.warning(f"[memory] skipping email {email_id}: memory unavailable ({reason})")
            return False
        try:
            logger.info(f"Processing email {email_id}")

            # The contact is the other party. A mail with no sender address
            # is a mechanical skip, as it always was: nothing to extract from,
            # nothing paid, the source marked so it is not retried.
            contact_email = email.get("from_email", "")
            if not contact_email:
                logger.warning(f"No contact email for {email_id}")
                self.storage.mark_email_processed(self.owner_id, email_id)
                return True

            source = self._source(
                "email", email_id, self._format_email_data(email, contact_email), "memory:email"
            )
            outcome = self._ingest(source, lambda: self._extract_entities(email, contact_email))
            if outcome.advances_checkpoint:
                self.storage.mark_email_processed(self.owner_id, email_id)
                return True
            logger.info(f"[memory] email {email_id} not settled: {outcome.outcome} {outcome.reason}")
            return False

        except BudgetError:
            raise
        except Exception as e:
            logger.error(f"Error processing email {email_id}: {e}", exc_info=True)
            return False

    def _source(self, kind: str, source_id: str, text: str, stage: str):
        """One rendered source, as the harness takes it."""
        Source, _ingest, _context = _harness()
        return Source(kind=kind, source_id=source_id, text=text, stage=stage)

    def _ingest(self, source, extract: Callable[[], Sequence[str]]):
        """One source through the harness, with this worker's wiring."""
        from zylch.memory.company_key import require_company_key

        _source, ingest, _context = _harness()
        if not self.merge_enabled:
            logger.warning(
                f"[memory] merge gate unhealthy — the role is shown no candidate for "
                f"{source.kind} {source.source_id}; every entity becomes a fresh blob"
            )
        return ingest(
            source,
            owner_id=self.owner_id,
            company_key=require_company_key(),
            extract=extract,
            client=self.decision_client,
            context=self._commit_context(retrieval=self.merge_enabled),
        )

    def _commit_context(self, *, retrieval: bool = True):
        """This worker's own storage and retrieval, as the harness expects them.

        ``retrieval=False`` is the merge-gate brake: search and the identity
        index answer nothing, exact reads stay.
        """
        _source, _ingest, CommitContext = _harness()

        def get_blob(blob_id):
            return self.blob_storage.get_blob(blob_id, self.owner_id)

        if not retrieval:
            return CommitContext(storage=self.blob_storage, get_blob=get_blob)
        return CommitContext(
            storage=self.blob_storage,
            get_blob=get_blob,
            search=lambda query, limit: self.hybrid_search.search(
                owner_id=self.owner_id, query=query, limit=limit
            ),
            identifier_blob_ids=lambda ids: self.storage.find_blobs_by_identifiers(
                owner_id=self.owner_id, identifiers=list(ids)
            ),
        )

    @bounded_operation(lambda self, *args, **kwargs: self.owner_id)
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
                try:
                    success = await self.process_email(email)
                except BudgetError:
                    stop = True
                    raise
                if success is None:
                    return
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

        results = await asyncio.gather(
            *[_process_one(e) for e in emails],
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result
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
                raise RuntimeError("Memory extraction prompt is not configured")

            email_data = self._format_email_data(
                email,
                contact_email,
            )

            # Route by whether the trained prompt actually uses old-style
            # {placeholder} tokens.
            #
            # The previous heuristic — call ``prompt_template.format(...)``
            # and treat "no exception raised" as "has placeholders" — was
            # inverted: a prompt with NO placeholders ALSO formats without
            # error (str.format is a no-op then), so it took the legacy
            # branch and was sent as a bare user message with the email
            # NEVER interpolated. The model received only the instructions
            # + few-shot examples and replied "no message content was
            # included", then echoed the prompt's OWN example entity. That
            # is how the bogus "John Doe / Acme / IT Consulting Offer"
            # PERSON and the ~440 duplicate TEMPLATE blobs were born — not
            # from real mail, but from the example bleeding through on every
            # email. Detect placeholders explicitly instead (mirrors
            # ``_extract_entities_for_message``).
            placeholder_tokens = (
                "{body}",
                "{from_email}",
                "{to_email}",
                "{cc_email}",
                "{subject}",
                "{date}",
                "{contact_email}",
            )
            if any(tok in prompt_template for tok in placeholder_tokens):
                # Legacy inline prompt → interpolate the email fields.
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
                with call_site("memory.extract"):
                    response = self.client.create_message_sync(
                        messages=[
                            {"role": "user", "content": prompt},
                        ],
                        max_tokens=EMAIL_EXTRACTION_MAX_TOKENS,
                    )
            else:
                # Modern cached-system prompt → instructions cached as the
                # system block, the actual email as the user message.
                system = [
                    {
                        "type": "text",
                        "text": prompt_template,
                        "cache_control": {
                            "type": "ephemeral",
                        },
                    },
                ]
                with call_site("memory.extract"):
                    response = self.client.create_message_sync(
                        system=system,
                        messages=[
                            {
                                "role": "user",
                                "content": ("Analyze this email:\n\n" + email_data),
                            },
                        ],
                        max_tokens=EMAIL_EXTRACTION_MAX_TOKENS,
                    )
            raw_output = complete_memory_text(response)
            logging.debug(f"RAW OUTPUT:\n{raw_output}")
            # Check for SKIP
            if raw_output.upper() == "SKIP":
                return []

            # Split by entity delimiter
            entities = self._parse_entities(raw_output)
            return entities

        except Exception as e:
            logger.error(f"Failed to extract entities: {e}")
            raise

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
            raise ValueError("Multiple extracted identities without an entity delimiter")
        else:
            # Single entity
            parts = [raw_output]
            logging.debug(f"Entities delimiter NOT found: {parts}")

        for part in parts:
            part = part.strip()
            # Validate
            if part and "#IDENTIFIERS" in part.upper():
                entities.append(part)
            elif part:
                raise ValueError("Extracted entity is missing its structured identity block")
        if not entities:
            raise ValueError("Empty extraction response; expected entities or SKIP")
        return entities

    # =========================================================
    # WhatsApp message processing (whatsapp-pipeline-parity Phase 2c)
    # =========================================================

    # Skip messages shorter than this — single emoji, "ok", "ciao" — that
    # carry no extractable identity / context. Same threshold the deleted
    # 2026-04 skeleton used; we still mark them as processed so we don't
    # re-evaluate every Update.
    _WA_MIN_TEXT_LEN = 20

    @bounded_item("memory:whatsapp")
    async def process_whatsapp_message(self, message: Dict) -> bool:
        """Take one WhatsApp message through the harness.

        Mirror of ``process_email``. The per-message LLM prompt is the
        same channel-aware ``memory_message`` prompt the email path uses
        (Phase 2b); only the envelope shape passed as the user message
        differs, and that envelope is the rendered source whose digest is
        the revision — a voice note transcribed after a first pass is a new
        revision, never an old digest reused.

        v1: 1-on-1 messages only (the storage helper already filters
        ``is_group=False``).
        """
        wa_id = message.get("id", "unknown")
        try:
            # Body source: a voice note's transcription stands in for the
            # text (the raw `text` is just a "[voice]" placeholder).
            effective = (message.get("transcription") or message.get("text") or "").strip()
            is_voice = bool(message.get("media_type") in ("voice", "audio")) and bool(
                message.get("transcription")
            )
            # A deliberate voice note is signal even when short ("Richiamami"),
            # so the <20 gate does not apply to transcribed audio; plain text
            # still gets the short-text skip — mechanical, unpaid, and marked
            # so the message is not re-evaluated every tick.
            too_short = len(effective) < (1 if is_voice else self._WA_MIN_TEXT_LEN)
            if too_short:
                logger.debug(
                    f"[memory] WA {wa_id} skipped — body too short "
                    f"(len={len(effective)}, is_voice={is_voice})"
                )
                self.storage.mark_whatsapp_memory_processed(self.owner_id, wa_id)
                return True

            envelope = self._format_whatsapp_data(message)
            source = self._source("whatsapp", wa_id, envelope, "memory:whatsapp")
            outcome = self._ingest(
                source,
                lambda: self._extract_entities_for_message(envelope=envelope, channel_label="WhatsApp"),
            )
            if outcome.advances_checkpoint:
                self.storage.mark_whatsapp_memory_processed(self.owner_id, wa_id)
                return True
            logger.info(f"[memory] WA {wa_id} not settled: {outcome.outcome} {outcome.reason}")
            return False

        except BudgetError:
            raise
        except Exception as e:
            logger.error(f"Error processing WhatsApp message {wa_id}: {e}", exc_info=True)
            return False

    @bounded_operation(lambda self, *args, **kwargs: self.owner_id)
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
        logger.info(f"Processing batch of {len(messages)} WA messages (concurrency={concurrency})")
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
                try:
                    ok = await self.process_whatsapp_message(msg)
                except BudgetError:
                    stop = True
                    raise
                if ok is None:
                    return
                if ok:
                    processed += 1
                    failures = 0
                else:
                    failures += 1
                    if failures >= 3:
                        logger.error("3 consecutive WA failures — stopping batch (check API key)")
                        stop = True

        results = await asyncio.gather(
            *[_process_one(m) for m in messages],
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result
        logger.info(f"WA batch complete: {processed}/{len(messages)} processed")
        return processed

    def _resolve_whatsapp_phone(self, sender_jid: str) -> str:
        """Resolve a WhatsApp ``sender_jid`` to a ``+<digits>`` phone, or ''.

        For real-number JIDs (``<digits>@s.whatsapp.net``) the phone is
        the local-part. For privacy-mode LIDs (``<digits>@lid``) the
        local-part is a pseudonym; we look up the real phone in
        ``whatsapp_contacts`` (populated locally by
        ``WhatsAppSyncService.sync_lid_contacts`` from whatsmeow's
        ``whatsmeow_lid_map``). Returns '' when the JID is empty, isn't
        WhatsApp-shaped, or the LID has no known phone — callers treat
        '' as "no contact_identifier".

        Used by ``_format_whatsapp_data`` to supply the sender identity
        to the LLM. The LLM decides which extracted entity owns that identity.
        """
        if not sender_jid:
            return ""
        if "@s.whatsapp.net" in sender_jid:
            digits = sender_jid.split("@", 1)[0]
            return "+" + digits if digits else ""
        if "@lid" in sender_jid:
            try:
                contact = self.storage.get_whatsapp_contact_by_jid(self.owner_id, sender_jid)
            except Exception as e:
                logger.warning(f"[memory] LID resolve failed for {sender_jid}: {e}")
                return ""
            if contact:
                resolved = (contact.get("phone_number") or "").strip()
                if resolved.startswith("+"):
                    return resolved
            return ""
        return ""

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
        # Prefer the voice-note transcription over the raw `text` (which is
        # only a "[voice]" placeholder for audio messages).
        text = message.get("transcription") or message.get("text") or ""

        # Resolve the sender phone for the From line via the shared
        # helper (single source of truth for LID→phone). WA stores the
        # JID canonicalised: digits + '@s.whatsapp.net' for real phone
        # numbers, digits + '@lid' for privacy-mode pseudonyms.
        phone = self._resolve_whatsapp_phone(sender_jid)
        lid = sender_jid if "@lid" in sender_jid else ""
        # LID → sender_name resolution (phone already resolved above).
        # Critical for cross-channel identity: an email blob about John
        # carries Phone: +393331... and a WhatsApp message from John
        # arrives with sender_jid=<lid>@lid. Without this lookup the
        # WA blob can't match the email blob.
        if lid and not sender_name:
            try:
                contact = self.storage.get_whatsapp_contact_by_jid(self.owner_id, sender_jid)
            except Exception as e:
                logger.warning(f"[memory] LID resolve failed for {sender_jid}: {e}")
                contact = None
            if contact:
                sender_name = contact.get("name") or contact.get("push_name") or sender_name

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
                raise RuntimeError("Memory extraction prompt is not configured")

            system = [
                {
                    "type": "text",
                    "text": prompt_template,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
            user_text = f"Analyze this message:\n\n{envelope}"
            with call_site("memory.extract"):
                response = self.client.create_message_sync(
                    system=system,
                    messages=[{"role": "user", "content": user_text}],
                    max_tokens=1024,
                )
            raw_output = complete_memory_text(response)
            if raw_output.upper() == "SKIP":
                return []
            return self._parse_entities(raw_output)
        except Exception as e:
            logger.error(f"Failed to extract entities ({channel_label}): {e}")
            raise

    @bounded_item("memory:calendar")
    async def process_calendar_event(self, event: Dict) -> bool:
        """Take one calendar event through the harness.

        The calendar extraction yields prose, not a structured entity; the
        role reads it as the suggestion and decides what memory it is, with
        the rendered event as the observation. "No significant facts." is an
        empty extraction: a recorded skip that marks the event.

        Args:
            event: Event dict with id, summary, description, location, start_time, end_time, attendees

        Returns:
            True if the source is settled, False otherwise
        """
        event_id = event.get("id", "unknown")
        try:
            logger.debug(f"Processing calendar event {event_id}")
            source = self._source(
                "calendar", event_id, self._format_calendar_data(event), "memory:calendar"
            )

            def extract() -> List[str]:
                facts = self._extract_calendar_facts(event)
                if not facts or facts == "No significant facts.":
                    return []
                return [facts]

            outcome = self._ingest(source, extract)
            if outcome.advances_checkpoint:
                self.storage.mark_calendar_event_processed(self.owner_id, event_id)
                return True
            logger.info(f"[memory] event {event_id} not settled: {outcome.outcome} {outcome.reason}")
            return False

        except BudgetError:
            raise
        except Exception as e:
            logger.error(f"Error processing event {event_id}: {e}", exc_info=True)
            return False

    @bounded_operation(lambda self, *args, **kwargs: self.owner_id)
    async def process_calendar_batch(self, events: List[Dict]) -> int:
        """Process batch of calendar events.

        Args:
            events: List of event dicts (from get_unprocessed_calendar_events)

        Returns:
            Number of successfully processed events
        """
        logger.info(f"Processing batch of {len(events)} calendar events")
        processed = 0

        failures = 0
        for event in events:
            success = await self.process_calendar_event(event)
            if success is None:
                continue
            if success:
                processed += 1
                failures = 0
            else:
                failures += 1
                if failures >= 3:
                    break

        logger.info(f"Calendar batch complete: {processed}/{len(events)} processed")
        return processed

    def _format_calendar_data(self, event: Dict) -> str:
        """Render a calendar event as the block the extraction prompt carries.

        The same text is the source the harness digests as the revision, so
        an edited event (a changed description, a new attendee) is a new
        revision.
        """
        attendees = event.get("attendees", [])
        if isinstance(attendees, list):
            attendees_str = ", ".join(
                a.get("email", "") if isinstance(a, dict) else str(a) for a in attendees
            )
        else:
            attendees_str = str(attendees)
        return (
            f"TITLE: {event.get('summary', '(no title)')}\n"
            f"DATE/TIME: {event.get('start_time', '')} - {event.get('end_time', '')}\n"
            f"LOCATION: {event.get('location', '(no location)')}\n"
            f"ATTENDEES: {attendees_str}\n"
            f"DESCRIPTION: {event.get('description', '(no description)')}"
        )

    def _extract_calendar_facts(self, event: Dict) -> str:
        """Extract facts from calendar event using LLM.

        Args:
            event: Calendar event dict

        Returns:
            Extracted facts as natural language string
        """
        try:
            prompt = f"""Extract key facts about attendees from this calendar event.

{self._format_calendar_data(event)}

---

Write a concise summary of what we learned from this meeting.
Include:
- Who attended and their relationship to the meeting
- Meeting purpose and topics discussed
- Any action items or follow-ups implied
- Context about the attendees (companies, roles if mentioned)

Output ONLY the facts as natural language prose (2-5 sentences). If no meaningful facts, output "No significant facts."
"""

            with call_site("memory.extract"):
                response = self.client.create_message_sync(
                    messages=[{"role": "user", "content": prompt}], max_tokens=512
                )
            facts = complete_memory_text(response)
            if not facts:
                raise ValueError("Empty calendar extraction response")
            return facts

        except Exception as e:
            logger.error(f"Failed to extract calendar facts: {e}")
            raise

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

    @bounded_item("memory:mrcall")
    async def process_mrcall_conversation(self, conversation: Dict) -> bool:
        """Take one MrCall conversation through the harness.

        Args:
            conversation: Conversation dict from mrcall_conversations table

        Returns:
            True if the source is settled, False otherwise
        """
        conv_id = conversation.get("id", "unknown")
        try:
            logger.info(f"Processing MrCall conversation {conv_id}")
            source = self._source(
                "mrcall", conv_id, self._format_mrcall_data(conversation), "memory:mrcall"
            )
            outcome = self._ingest(source, lambda: self._extract_mrcall_entities(conversation))
            if outcome.advances_checkpoint:
                self.storage.mark_mrcall_memory_processed(self.owner_id, conv_id)
                return True
            logger.info(f"[memory] conversation {conv_id} not settled: {outcome.outcome} {outcome.reason}")
            return False

        except BudgetError:
            raise
        except Exception as e:
            logger.error(f"Error processing conversation {conv_id}: {e}", exc_info=True)
            return False

    def _format_mrcall_data(self, conversation: Dict) -> str:
        """Render a MrCall conversation as the source the harness digests."""
        duration_ms = conversation.get("call_duration_ms", 0)
        duration_seconds = duration_ms / 1000 if duration_ms else 0
        return (
            f"Channel: MrCall\n"
            f"Contact: {conversation.get('contact_name', 'unknown')} "
            f"({conversation.get('contact_phone', 'unknown')})\n"
            f"At: {conversation.get('call_started_at', 'unknown')}\n"
            f"Duration: {int(duration_seconds)} seconds\n\n"
            f"{self._extract_conversation_text(conversation.get('body'))}"
        )

    @bounded_operation(lambda self, *args, **kwargs: self.owner_id)
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
            if success is None:
                continue
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
                raise RuntimeError("MrCall memory extraction prompt is not configured")

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

            with call_site("memory.extract"):
                response = self.client.create_message_sync(
                    messages=[{"role": "user", "content": prompt}], max_tokens=1024
                )
            raw_output = complete_memory_text(response)
            logger.debug(f"MrCall RAW OUTPUT:\n{raw_output}")

            if raw_output.upper() == "SKIP":
                return []

            entities = self._parse_entities(raw_output)
            return entities

        except Exception as e:
            logger.error(f"Failed to extract MrCall entities: {e}")
            raise

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
