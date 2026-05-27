"""WhatsApp thread-row construction + message search.

Two responsibilities, both pure SQLAlchemy over the local store so they
are unit-testable without a live neonize socket:

* :func:`build_thread_rows` — turn an *ordered* list of ``chat_jid``s into
  the thread dicts the desktop WhatsApp tab renders. Extracted from
  ``rpc/whatsapp_actions.whatsapp_list_threads`` so the plain listing and
  the search results render through the SAME display logic (name fallback
  chain, phone resolution, LID/group handling, preview).
* :func:`search_thread_jids` — find the chats matching a free-text query.
  Matches message ``text`` / ``transcription`` / ``sender_name`` AND
  contact ``name`` / ``push_name`` / ``phone_number`` (so a name-only
  filter is a strict subset), returns the matching chat_jids newest-first
  plus a per-chat snippet of the matching message.

Both deliberately mirror ``list_threads``' broadcast/newsletter/empty-jid
exclusion so search can never surface a row the listing would hide.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _escape_like(value: str) -> str:
    """Escape SQL LIKE wildcards in user input (matches whatsapp_tools)."""
    return value.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def build_thread_rows(
    session,
    owner_id: str,
    jids: List[str],
    snippet_by_jid: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Build thread dicts for ``jids``, preserving the given order.

    Args:
        session: an open SQLAlchemy session.
        owner_id: active profile owner id.
        jids: ordered chat_jids (the row order is preserved verbatim —
            callers sort upstream by recency / relevance).
        snippet_by_jid: optional ``{chat_jid: matching message text}`` to
            attach as ``match_snippet`` on each row (search use). The full
            text is passed through untruncated; the renderer clamps it.

    Returns:
        One dict per jid with: jid, name, phone, is_group, message_count,
        last_at, last_preview, last_from_me (+ match_snippet when given).
    """
    from sqlalchemy import func

    from zylch.storage.models import WhatsAppContact, WhatsAppMessage

    if not jids:
        return []

    # Message count per chat — same value list_threads' aggregate carried.
    count_rows = (
        session.query(
            WhatsAppMessage.chat_jid,
            func.count(WhatsAppMessage.id).label("c"),
        )
        .filter(
            WhatsAppMessage.owner_id == owner_id,
            WhatsAppMessage.chat_jid.in_(jids),
        )
        .group_by(WhatsAppMessage.chat_jid)
        .all()
    )
    count_by_jid = {r.chat_jid: int(r.c or 0) for r in count_rows}

    # Latest message per chat (for preview + timestamp + direction) and
    # the latest INCOMING sender_name (for 1-on-1 display when no contact).
    last_msg_rows = (
        session.query(
            WhatsAppMessage.chat_jid,
            WhatsAppMessage.text,
            WhatsAppMessage.is_from_me,
            WhatsAppMessage.is_group,
            WhatsAppMessage.sender_name,
            WhatsAppMessage.timestamp,
            WhatsAppMessage.media_type,
        )
        .filter(
            WhatsAppMessage.owner_id == owner_id,
            WhatsAppMessage.chat_jid.in_(jids),
        )
        .order_by(WhatsAppMessage.timestamp.desc())
        .all()
    )
    last_by_jid: Dict[str, Any] = {}
    peer_name_by_jid: Dict[str, str] = {}
    for r in last_msg_rows:
        if r.chat_jid not in last_by_jid:
            last_by_jid[r.chat_jid] = r
        if r.chat_jid not in peer_name_by_jid and not bool(r.is_from_me) and r.sender_name:
            peer_name_by_jid[r.chat_jid] = r.sender_name

    contact_rows = (
        session.query(WhatsAppContact)
        .filter(
            WhatsAppContact.owner_id == owner_id,
            WhatsAppContact.jid.in_(jids),
        )
        .all()
    )
    contact_by_jid = {c.jid: c for c in contact_rows}

    rows: List[Dict[str, Any]] = []
    for jid in jids:
        last = last_by_jid.get(jid)
        contact = contact_by_jid.get(jid)
        is_group = bool(last.is_group) if last is not None else jid.endswith("@g.us")
        # `@lid` local-parts are privacy pseudonyms, not phones; `@g.us`
        # local-parts are synthetic group ids. Never render either as a phone.
        is_lid = jid.endswith("@lid")
        name = None
        phone = None
        if contact is not None:
            name = contact.name or contact.push_name
            phone = contact.phone_number
        if not name and not is_group:
            peer = peer_name_by_jid.get(jid)
            if peer:
                name = peer
        if not phone and not is_group and not is_lid:
            bare = jid.split("@", 1)[0]
            phone = bare or None

        if last is None:
            preview = ""
        elif last.text:
            preview = last.text
        elif last.media_type:
            preview = f"[{last.media_type}]"
        else:
            preview = ""

        row: Dict[str, Any] = {
            "jid": jid,
            "name": name,
            "phone": phone,
            "is_group": is_group,
            "message_count": count_by_jid.get(jid, 0),
            "last_at": (
                last.timestamp.isoformat()
                if last is not None and last.timestamp is not None
                else None
            ),
            "last_preview": preview,
            "last_from_me": bool(last.is_from_me) if last is not None else False,
        }
        if snippet_by_jid is not None:
            row["match_snippet"] = snippet_by_jid.get(jid)
        rows.append(row)
    return rows


def search_thread_jids(
    session,
    owner_id: str,
    query: str,
    limit: int = 200,
) -> Tuple[List[str], Dict[str, str]]:
    """Find chats matching ``query``, newest-first.

    A chat matches when any of its messages' ``text`` / ``transcription``
    / ``sender_name`` contains the query, OR a contact row for the chat
    matches on ``name`` / ``push_name`` / ``phone_number``, OR (when the
    query contains a phone-like digit run) the chat_jid or contact phone
    contains those digits.

    Args:
        session: an open SQLAlchemy session.
        owner_id: active profile owner id.
        query: free-text query (already user-entered; whitespace-trimmed
            here). Empty → no results.
        limit: max chats to return.

    Returns:
        ``(ordered_jids, snippet_by_jid)`` — chat_jids ordered by most
        recent activity, and the matching message text per chat (only for
        chats matched via message content; contact-only matches have no
        snippet).
    """
    from sqlalchemy import func, or_

    from zylch.storage.models import WhatsAppContact, WhatsAppMessage

    q = (query or "").strip()
    if not q or not owner_id:
        return [], {}

    like = f"%{_escape_like(q)}%"
    # A digit run long enough to be a meaningful phone fragment (avoids a
    # bare "3" matching every Italian number). 4 digits is the floor.
    digits = re.sub(r"\D", "", q)
    digits = digits if len(digits) >= 4 else ""

    # Shared exclusion: real conversations only (mirror list_threads).
    not_junk = [
        WhatsAppMessage.chat_jid.isnot(None),
        WhatsAppMessage.chat_jid != "",
        ~WhatsAppMessage.chat_jid.like("%@broadcast"),
        ~WhatsAppMessage.chat_jid.like("%@newsletter"),
    ]

    # ── 1. Message-content matches (carry a snippet + recency) ──────────
    msg_predicates = [
        WhatsAppMessage.text.ilike(like, escape="\\"),
        WhatsAppMessage.transcription.ilike(like, escape="\\"),
        WhatsAppMessage.sender_name.ilike(like, escape="\\"),
    ]
    if digits:
        msg_predicates.append(WhatsAppMessage.chat_jid.like(f"%{digits}%"))

    matching_msgs = (
        session.query(
            WhatsAppMessage.chat_jid,
            WhatsAppMessage.text,
            WhatsAppMessage.transcription,
            WhatsAppMessage.timestamp,
        )
        .filter(
            WhatsAppMessage.owner_id == owner_id,
            *not_junk,
            or_(*msg_predicates),
        )
        .order_by(WhatsAppMessage.timestamp.desc())
        .all()
    )
    snippet_by_jid: Dict[str, str] = {}
    candidate_jids: set[str] = set()
    ql = q.lower()
    for r in matching_msgs:
        candidate_jids.add(r.chat_jid)
        if r.chat_jid not in snippet_by_jid:
            # Show the field that actually contains the query. A voice note
            # stores ``text='[voice]'`` with the words in ``transcription``;
            # blindly preferring ``text`` would show "[voice]" for a hit
            # that lives in the transcript.
            text_s = (r.text or "").strip()
            trans_s = (r.transcription or "").strip()
            if ql in text_s.lower():
                snip = text_s
            elif ql in trans_s.lower():
                snip = trans_s
            else:
                snip = text_s or trans_s
            if snip:
                snippet_by_jid[r.chat_jid] = snip

    # ── 2. Contact matches (name / push_name / phone) ──────────────────
    contact_predicates = [
        WhatsAppContact.name.ilike(like, escape="\\"),
        WhatsAppContact.push_name.ilike(like, escape="\\"),
        WhatsAppContact.phone_number.ilike(like, escape="\\"),
    ]
    if digits:
        contact_predicates.append(WhatsAppContact.phone_number.ilike(f"%{digits}%", escape="\\"))
    contact_jids = (
        session.query(WhatsAppContact.jid)
        .filter(
            WhatsAppContact.owner_id == owner_id,
            or_(*contact_predicates),
        )
        .all()
    )
    for (jid,) in contact_jids:
        if jid:
            candidate_jids.add(jid)

    if not candidate_jids:
        return [], {}

    # ── 3. Order all candidates by most recent activity ────────────────
    # Contact-only matches have no message snippet but still need a
    # recency key; a single grouped query gives every candidate its
    # latest timestamp (and re-applies the junk exclusion in case a
    # contact row pointed at a broadcast jid).
    recency_rows = (
        session.query(
            WhatsAppMessage.chat_jid,
            func.max(WhatsAppMessage.timestamp).label("last_ts"),
        )
        .filter(
            WhatsAppMessage.owner_id == owner_id,
            WhatsAppMessage.chat_jid.in_(list(candidate_jids)),
            *not_junk,
        )
        .group_by(WhatsAppMessage.chat_jid)
        .order_by(func.max(WhatsAppMessage.timestamp).desc())
        .limit(limit)
        .all()
    )
    ordered = [r.chat_jid for r in recency_rows]
    logger.debug(
        f"[wa-search] owner_id={owner_id} query={q!r} -> "
        f"{len(ordered)} chats ({len(snippet_by_jid)} with snippet)"
    )
    return ordered, snippet_by_jid
