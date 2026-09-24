"""The learned-rules store — what may enter it, and what comes back out.

The always-on OPERATING RULES block is built from the blob namespaces
``template:<owner>`` (canonical since 2026-05-22) and ``prefs:<owner>``
(legacy, still read). Every rule in there is injected VERBATIM into
every task-detection, reanalysis, solve, chat and emailer prompt. It is
the most expensive real estate in the engine, and until now it had no
door: any writer could put anything in it, forever, and the only defence
was a read-time truncation that silently dropped the tail.

What that cost (support@, measured 2026-08-01): 82 blobs, 66,842 chars
against an 8,000-char soft cap — so EVERY detection call logged
``[prefs] learned preferences size 67004 chars exceeds soft cap 8000``
and ran on a truncated view. 81 of those 82 blobs were not rules at all
but memory ENTITIES (``#IDENTIFIERS`` / ``Entity type: STYLE`` —
trained-voice response patterns), 66,105 of the 66,842 chars. There were
zero exact duplicates and many near-duplicates: seven separate
"phone number migration" STYLEs written in eight days.

Three defences, all here so no writer can skip one:

1. :func:`is_entity_shaped` — an entity blob may not enter a rule
   namespace. That is the runaway class; it belongs in ``user:``, where
   it is retrieved by relevance search instead of pinned into every
   prompt.
2. Exact / normalised duplicate detection — the same rule written twice
   is stored once.
3. Substring supersession — a new rule that CONTAINS an existing one
   (or is contained by it) updates that blob in place instead of adding
   another near-copy. Deterministic compaction, no LLM.

With (1)–(3) the store converges: it grows only when the user teaches
something genuinely new. (1) and the exact-duplicate half of (2) are
deterministic and unpaid; the supersession in (3) and every new rule are
semantic writes and go through the mnemonic harness, the candidate pinned
and the text it replaces retained. The read side (:func:`select_within_cap`)
then selects by PRIORITY and RECENCY rather than by byte position, so a stray
never evicts a real rule; and :mod:`scripts.compact_learned_prefs`
repairs a store that already blew up.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

#: Soft cap (characters) on what the read side injects into a prompt.
#: Live ``os.environ`` read at call time, NOT the frozen pydantic
#: settings — a ``settings.update`` must take effect without a daemon
#: restart (precedent: LLM_DAILY_BUDGET_USD, TASK_BACKLOG_MAX_AGE_DAYS).
DEFAULT_LEARNED_PREFS_MAX_CHARS = 8000


def learned_prefs_max_chars() -> int:
    """Soft cap in characters, read LIVE from ``os.environ``."""
    raw = os.environ.get("LEARNED_PREFS_MAX_CHARS")
    if raw is None or str(raw).strip() == "":
        return DEFAULT_LEARNED_PREFS_MAX_CHARS
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        logger.warning(
            f"[prefs] invalid LEARNED_PREFS_MAX_CHARS={raw!r} — using default "
            f"{DEFAULT_LEARNED_PREFS_MAX_CHARS}"
        )
        return DEFAULT_LEARNED_PREFS_MAX_CHARS
    if value <= 0:
        logger.warning(f"[prefs] LEARNED_PREFS_MAX_CHARS={value} is not positive — using default")
        return DEFAULT_LEARNED_PREFS_MAX_CHARS
    return value


def rule_namespaces(owner_id: str) -> List[str]:
    """The namespaces the OPERATING RULES block is built from."""
    return [f"template:{owner_id}", f"prefs:{owner_id}"]


def is_entity_shaped(content: str) -> bool:
    """True when ``content`` is a memory ENTITY blob, not a rule.

    Keyed on the memory extractor's own section markers. A rule is prose
    ("Never promise a callback time"); an entity is the three-section
    ``#IDENTIFIERS`` / ``#ABOUT`` / ``#HISTORY`` record, or a flat FACT.
    """
    if not content:
        return False
    head = content.strip().lower()
    if head.startswith("#identifiers"):
        return True
    # `Entity type: X` appears on line 2 of every entity blob.
    for line in head.splitlines()[:4]:
        if line.strip().startswith("entity type:"):
            return True
    return False


# The section markers the mnemonic role writes; a rule's control header sits
# between ``#IDENTIFIERS`` and ``#ABOUT``.
_SECTION_MARKERS = ("#IDENTIFIERS", "#ABOUT", "#HISTORY")


def rule_body(content: str) -> str:
    """The rule's own text, with the STYLE control header stripped.

    A rule the harness writes carries the minimal header the role writes for
    every memory — ``#IDENTIFIERS`` / ``Entity type: STYLE`` / ``Scope:
    account`` — and the ``#ABOUT`` / ``#HISTORY`` markers. The header is
    control metadata, not instruction: rendering strips it and keeps the rule
    text, and duplicate detection compares the text. A legacy plain rule has
    no header and comes back unchanged; an entity blob's header (any other
    type) is kept, so :func:`is_entity_shaped` still sees it.
    """
    text = (content or "").strip()
    if not text.upper().startswith("#IDENTIFIERS"):
        return text
    lines = text.splitlines()
    header = []
    for line in lines[1:]:
        if line.strip().upper() in _SECTION_MARKERS:
            break
        if line.strip():
            header.append(line.strip().lower())
    # Only the rule's own control header is stripped: exactly the type and the
    # scope. A header carrying a Name, an Email or anything else is an
    # entity-shaped stray — the runaway class the shape guard exists for —
    # and keeps its header so the guard and the ranking still see it.
    if "entity type: style" not in header or any(
        not (line == "entity type: style" or line.startswith("scope:")) for line in header
    ):
        return text
    kept = []
    in_header = True
    for line in lines[1:]:
        stripped = line.strip()
        if stripped.upper() in _SECTION_MARKERS:
            in_header = False
            continue
        if in_header:
            continue
        kept.append(line)
    return "\n".join(kept).strip() or text


def normalise(content: str) -> str:
    """Whitespace/case-insensitive key used for duplicate detection.

    Two rules that differ only in casing, indentation or line wrapping
    are the same rule; storing both doubles their prompt cost and gives
    the model two voices for one instruction. Compared on the rule's own
    text (:func:`rule_body`), so a rule the harness wrote under its control
    header and the same rule offered again are one rule.
    """
    return re.sub(r"\s+", " ", rule_body(content).strip().lower())


def load_rules(owner_id: str) -> List[Dict[str, Any]]:
    """Every rule blob for ``owner_id``, oldest first.

    Returns dicts with ``id`` / ``namespace`` / ``content`` /
    ``created_at``. Never raises: a broken read degrades to "no rules",
    exactly as the previous inline query did.
    """
    try:
        from zylch.storage.database import get_session
        from zylch.storage.models import Blob
    except Exception as e:
        logger.warning(f"[prefs] cannot import Blob/get_session: {e}")
        return []

    try:
        from zylch.memory.company_key import require_company_key

        key = require_company_key()
        with get_session() as session:
            rows = (
                session.query(Blob)
                .filter(
                    Blob.company_key == key,
                    Blob.owner_id == owner_id,
                    Blob.namespace.in_(rule_namespaces(owner_id)),
                )
                .order_by(Blob.created_at.asc())
                .all()
            )
            return [
                {
                    "id": str(r.id),
                    "namespace": r.namespace,
                    "content": r.content,
                    "created_at": r.created_at,
                }
                for r in rows
                if (r.content or "").strip()
            ]
    except Exception as e:
        logger.warning(f"[prefs] query failed for owner {owner_id!r}: {e}")
        return []


def select_within_cap(
    rules: Sequence[Dict[str, Any]],
    cap: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Choose which rules fit in ``cap`` chars. Returns ``(kept, dropped)``.

    Selection is by PRIORITY then RECENCY, never by byte position:

    1. genuine rules outrank entity-shaped strays — a misrouted style
       blob must never evict an operating rule the user actually taught;
    2. within a class, newest first — the user's latest correction is
       the one most likely to still be true;
    3. an item that does not fit is SKIPPED, not treated as a stop
       signal. The old loop ``break``-ed on the first oversized chunk,
       so one 5 KB stray could hide every smaller rule behind it.

    ``kept`` comes back in stable ``created_at`` order so the rendered
    block is byte-identical between turns and the prompt cache re-hits.
    """
    if cap is None:
        cap = learned_prefs_max_chars()

    def _epoch(row: Dict[str, Any]) -> float:
        """created_at as a float. Undated rows sort oldest — a row with no
        timestamp cannot claim to be the user's most recent instruction."""
        value = row.get("created_at")
        try:
            return float(value.timestamp())
        except (AttributeError, TypeError, ValueError):
            return 0.0

    ordered = sorted(
        rules,
        key=lambda r: (
            1 if is_entity_shaped(rule_body(r.get("content") or "")) else 0,
            -_epoch(r),
        ),
    )
    kept: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []
    total = 0
    for r in ordered:
        size = len(r.get("content") or "")
        # +2 for the "\n\n" separator each additional entry costs.
        cost = size + (2 if kept else 0)
        if total + cost > cap:
            dropped.append(r)
            continue
        kept.append(r)
        total += cost
    kept.sort(key=lambda r: (_epoch(r), str(r.get("id") or "")))
    return kept, dropped


def render(rules: Sequence[Dict[str, Any]]) -> str:
    """Join selected rule texts into the prompt block body, control headers stripped."""
    return "\n\n".join(rule_body(r.get("content") or "") for r in rules if (r.get("content") or ""))


def store_rule(
    owner_id: str,
    content: str,
    event_description: str,
    *,
    writer: str,
    entry=None,
) -> Dict[str, Any]:
    """The ONLY door into the rule namespaces. Returns an outcome dict.

    ``{"action": …, "blob_id": …, "reason": …}`` where ``action`` is one
    of ``created`` / ``superseded`` / ``duplicate`` / ``review`` / ``refused``
    / ``error``. Every outcome is logged with ``writer`` so a store that
    grows again can be traced to its source in one grep.

    The deterministic defences stay deterministic and unpaid: an entity-shaped
    text is refused, an identical rule is a duplicate, a rule contained in an
    existing one is a duplicate. Everything else is a semantic write and goes
    through the harness: the substring-supersession candidate, when one
    exists, is pinned as the event's target and named as the requested write,
    and the mnemonic role decides — through the retaining rewrite, never an
    overwrite. A store that is over the cap AFTER a legitimate write logs an
    ERROR naming the repair script — the write itself is never silently
    dropped, because losing a rule the user just taught is worse than an
    oversized store.

    ``entry`` is the admission and source the caller runs under
    (``zylch.memory.mnemonic.entry``); a caller that passes none gets the
    current turn's, or a refusal when it is inside a preparation run with no
    admitted item.
    """
    content = (content or "").strip()
    if not content:
        return {"action": "refused", "blob_id": None, "reason": "empty content"}

    if is_entity_shaped(content):
        logger.warning(
            f"[prefs] REFUSED entity-shaped blob from writer={writer} "
            f"({len(content)} chars): the rule namespaces hold operating "
            f"rules, not memory entities. Entities belong in "
            f"user:{owner_id}, where they are retrieved by relevance "
            f"instead of pinned into every prompt."
        )
        return {
            "action": "refused",
            "blob_id": None,
            "reason": (
                "entity-shaped content (#IDENTIFIERS / Entity type:) cannot be "
                "stored as an operating rule — use the user: namespace"
            ),
        }

    existing = load_rules(owner_id)
    key = normalise(content)

    for r in existing:
        if normalise(r["content"]) == key:
            logger.info(
                f"[prefs] duplicate rule from writer={writer} — already stored "
                f"as blob_id={r['id']}; nothing written"
            )
            return {"action": "duplicate", "blob_id": r["id"], "reason": "identical rule exists"}

    # Substring supersession — deterministic candidate selection. Only when
    # the containment is strict and the shorter side is substantial (a
    # two-word fragment inside a long rule is a coincidence, not a
    # superseded rule). The replacement itself is a semantic write: the
    # candidate is pinned and the role decides.
    candidate: Optional[Dict[str, Any]] = None
    for r in existing:
        other = normalise(r["content"])
        if len(other) < 40 or len(key) < 40:
            continue
        if other in key:
            candidate = r
            break
        if key in other:
            logger.info(
                f"[prefs] rule from writer={writer} is already contained in "
                f"blob_id={r['id']}; nothing written"
            )
            return {
                "action": "duplicate",
                "blob_id": r["id"],
                "reason": "contained in an existing rule",
            }

    result = _submit_rule(owner_id, content, entry, target=candidate, explicit=False)
    if isinstance(result, dict):
        return result
    if result.outcome == "committed":
        blob_id = result.committed_ids[0][0]
        if candidate is not None and blob_id == candidate["id"]:
            logger.info(
                f"[prefs] rule from writer={writer} SUPERSEDES blob_id={blob_id} "
                f"({len(candidate['content'])} → {len(content)} chars) — updated in "
                f"place instead of storing a near-copy"
            )
            return {"action": "superseded", "blob_id": blob_id, "reason": "extends an existing rule"}
        total = sum(len(rule_body(r["content"])) for r in existing) + len(content)
        cap = learned_prefs_max_chars()
        if total > cap:
            logger.error(
                f"[prefs] rule store is {total} chars, over the {cap}-char cap, after "
                f"a write from writer={writer}. The rule was stored (losing a taught "
                f"rule is worse), but prompts are now running on a truncated view. "
                f"Run scripts/compact_learned_prefs.py to compact it."
            )
        else:
            logger.debug(f"[prefs] rule stored by writer={writer}: {total}/{cap} chars used")
        return {"action": "created", "blob_id": blob_id, "reason": "new rule"}
    return _not_written(result, candidate["id"] if candidate else None, writer)


def refine_rule(
    owner_id: str,
    blob_id: str,
    content: str,
    event_description: str,
    *,
    writer: str,
    entry=None,
) -> Dict[str, Any]:
    """Rewrite one of this owner's rules in place — the only door for a refinement.

    ``{"action": …, "blob_id": …, "namespace": …, "reason": …}`` where
    ``action`` is ``refined`` / ``duplicate`` / ``review`` / ``refused`` /
    ``error``. The target must be one of the caller's own rule blobs: a
    behavioral rule must never be written onto a contact, so a company-family
    row is refused with its namespace named, and so is a row this owner cannot
    see. The text is held to the same shape rule as ``store_rule`` — an entity
    does not become a rule by being written over one. The rewrite itself is the
    harness's: the row is pinned as the requested target, the mnemonic role
    decides, and the text it replaces is retained.
    """
    content = (content or "").strip()
    if not content:
        return {"action": "refused", "blob_id": blob_id, "reason": "empty content"}
    if is_entity_shaped(content):
        logger.warning(
            f"[prefs] REFUSED entity-shaped refinement of blob_id={blob_id} from "
            f"writer={writer}: the rule namespaces hold operating rules, not entities."
        )
        return {
            "action": "refused",
            "blob_id": blob_id,
            "reason": (
                "entity-shaped content (#IDENTIFIERS / Entity type:) cannot be "
                "stored as an operating rule — use the user: namespace"
            ),
        }
    existing = _blob_storage().get_blob(blob_id=blob_id, owner_id=owner_id)
    if not existing:
        return {
            "action": "refused",
            "blob_id": blob_id,
            "reason": (
                f"No blob with id={blob_id!r} for this owner. Did you call "
                "search_local_memory first to obtain a real id?"
            ),
        }
    namespace = existing.get("namespace") or ""
    if namespace not in rule_namespaces(owner_id):
        logger.warning(
            f"[prefs] REFUSED rule from writer={writer} onto blob_id={blob_id} "
            f"(namespace {namespace}): a rule never overwrites a contact."
        )
        return {
            "action": "refused",
            "blob_id": blob_id,
            "reason": (
                "A behavioral rule must not be written onto a contact blob "
                f"(namespace {namespace}). Save it with "
                "create_memory(entry_type='behavioral_rule') — it goes to the "
                "always-on rules, never a contact."
            ),
        }
    target = {"id": str(existing["id"]), "content": existing.get("content") or ""}
    result = _submit_rule(owner_id, content, entry, target=target, explicit=True)
    if isinstance(result, dict):
        return result
    if result.outcome == "committed":
        written = result.committed_ids[0][0]
        if written != blob_id:
            namespace = (_blob_storage().get_blob(written, owner_id) or {}).get("namespace") or namespace
        logger.info(f"[prefs] rule blob_id={written} refined by writer={writer}")
        return {
            "action": "refined",
            "blob_id": written,
            "namespace": namespace,
            "reason": "rule refined in place",
        }
    return _not_written(result, blob_id, writer)


def _submit_rule(owner_id: str, content: str, entry, *, target: Optional[Dict[str, Any]], explicit: bool):
    """One STYLE event through the harness. Returns the result, or a refusal dict."""
    from zylch.memory.company_key import require_company_key
    from zylch.memory.mnemonic import submit
    from zylch.memory.mnemonic.approval import RequestedWrite
    from zylch.memory.mnemonic.contracts import (
        ACCOUNT_SCOPE,
        CREATE,
        OPERATOR_DELEGATED,
        STYLE,
        UPDATE,
        MemoryEvent,
        SubjectHint,
    )
    from zylch.memory.mnemonic.entry import EntryRefused, entry_for

    try:
        entry = entry or entry_for(fallback=content)
    except EntryRefused as exc:
        return {"action": "refused", "blob_id": target["id"] if target else None, "reason": str(exc)}
    try:
        company_key = require_company_key()
    except RuntimeError as exc:
        return {"action": "error", "blob_id": target["id"] if target else None, "reason": str(exc)}
    event = MemoryEvent(
        owner_id=owner_id,
        company_key=company_key,
        caller_class=OPERATOR_DELEGATED,
        origin=entry.origin,
        source_kind=entry.source_kind,
        source_id=entry.source_id,
        source_revision=entry.source_revision,
        observation=entry.observation,
        subject_hint=SubjectHint(entity_type=STYLE, target_blob_id=target["id"] if target else None),
        explicit_request=explicit,
        stage=entry.stage,
        cancellation=entry.cancellation,
    ).with_model_arguments({"content": content})
    requested = (
        RequestedWrite(
            action=UPDATE,
            blob_id=target["id"],
            entity_type=STYLE,
            scope=ACCOUNT_SCOPE,
            subject_is_authoritative=True,
        )
        if target
        else RequestedWrite(action=CREATE, entity_type=STYLE, scope=ACCOUNT_SCOPE)
    )
    return submit(event, requested=requested)


def _not_written(result, blob_id: Optional[str], writer: str) -> Dict[str, Any]:
    """The outcome dict for a submission that wrote nothing."""
    if result.outcome == "skipped":
        target = result.proposal.no_op_target if result.proposal else None
        logger.info(f"[prefs] rule from writer={writer} already recorded: {result.reason}")
        return {
            "action": "duplicate",
            "blob_id": target.blob_id if target else blob_id,
            "reason": result.reason,
        }
    if result.outcome == "review_needed":
        logger.info(f"[prefs] rule from writer={writer} needs review: {result.reason}")
        return {"action": "review", "blob_id": blob_id, "reason": result.reason}
    logger.warning(f"[prefs] rule from writer={writer} not written: {result.reason}")
    return {"action": "error", "blob_id": blob_id, "reason": result.reason}


def _blob_storage():
    from zylch.memory import EmbeddingEngine, MemoryConfig
    from zylch.memory.blob_storage import BlobStorage
    from zylch.storage.database import get_session

    return BlobStorage(get_session, EmbeddingEngine(MemoryConfig()))
