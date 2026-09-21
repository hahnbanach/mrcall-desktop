"""Message-ID normalisation for reply threading.

`In-Reply-To` and `References` are not free text: every entry is an RFC 5322
`msg-id`, `<id-left@id-right>`. A value that is not one is worse than an absent
header. The recipient's client cannot thread the reply, so the answer arrives
as a new conversation; and `services/solve_tools.py` looks the parent up by
`Email.message_id_header == in_reply_to`, so the sent mirror is filed under a
new thread and the conversation reads as unanswered from then on.

The threading arguments reach `storage.create_draft` as free strings chosen by
the model — `assistant/prompts.py` instructs it to copy the id out of a
`search_emails` result — and nothing between that call and the SMTP socket
inspected them. The malformation observed in the wild is HTML entity escaping,
`&lt;id@host&gt;`, emitted by the model although the search result it read
carried the plain `<id@host>`.

These helpers repair what can be repaired and drop what cannot, at the two
boundaries that matter: persisting a draft, and building the MIME message.
Dropping is the deliberate failure mode — a missing reference costs threading
on one message, an invalid one also poisons every later match on that thread.
"""

import html
import logging
import re
from typing import Any, List, Optional, Union

logger = logging.getLogger(__name__)

# `<id-left@id-right>`: no whitespace, no nested angle brackets, one `@` at
# minimum. Deliberately permissive about the rest — real ids in the wild carry
# `+`, `=`, `/` and dots, and rejecting a deliverable id helps nobody.
_MSGID = re.compile(r"^<[^<>\s]+@[^<>\s]+>$")
_BARE = re.compile(r"^[^<>\s]+@[^<>\s]+$")


def clean_message_id(value: Optional[str]) -> Optional[str]:
    """One `msg-id`, normalised, or None when it cannot be made valid.

    Unescapes HTML entities, folds the line breaks a folded header leaves
    behind, and adds the angle brackets when a bare `local@domain` arrives.
    """
    if not value or not isinstance(value, str):
        return None
    candidate = html.unescape(value).strip()
    candidate = " ".join(candidate.split())
    if not candidate:
        return None
    if _BARE.match(candidate):
        candidate = f"<{candidate}>"
    if not _MSGID.match(candidate):
        logger.warning(
            "[msgid] dropping unusable threading id %r (from %r)", candidate, value
        )
        return None
    return candidate


def clean_references(
    value: Union[str, List[str], None],
) -> Union[str, List[str], None]:
    """A `References` chain, normalised, keeping the caller's shape.

    A string in gives a space-joined string back (what the header wants); a
    list in gives a list back (what the drafts table stores). Entries that
    cannot be repaired are dropped individually — one bad id in a long chain
    must not cost the whole chain.
    """
    if value is None:
        return None
    was_list = isinstance(value, (list, tuple))
    if was_list:
        raw: List[Any] = list(value)
    elif isinstance(value, str):
        raw = html.unescape(value).split()
    else:
        return None
    cleaned = [c for c in (clean_message_id(str(item)) for item in raw) if c]
    if not cleaned:
        return [] if was_list else None
    return cleaned if was_list else " ".join(cleaned)
