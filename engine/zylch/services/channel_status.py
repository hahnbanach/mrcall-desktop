"""Live availability of each messaging channel, for the assistant prompt.

Injected into every chat turn (after the cache breakpoint, so it never
invalidates the cached prefix) so the model offers only channels that are
actually usable. Mario 2026-06-15: on an account with WhatsApp NOT connected,
the assistant offered to send via WhatsApp anyway. All checks here are local
and cheap (env var + file existence) — no network calls.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _whatsapp_paired() -> bool:
    """True iff a saved WhatsApp (neonize) session exists on disk.

    ``WhatsAppClient.has_session()`` is exactly ``Path(db_path).exists()``;
    we reuse its path helper so we don't construct the client (and pull in a
    live neonize handle) just to stat a file.
    """
    try:
        from zylch.whatsapp.client import _default_wa_db

        return Path(_default_wa_db()).exists()
    except Exception:
        return False


def _mrcall_signed_in() -> bool:
    """True iff a Firebase session is cached (MrCall credits / SMS / calls)."""
    try:
        from zylch.auth.session import get_session

        return get_session() is not None
    except Exception:
        return False


def get_channel_status_block() -> str:
    """Return a short live channel-status block for the system prompt.

    The assistant must only OFFER a channel marked ready; for one that is
    not, it should tell the user how to enable it instead of promising to
    send.
    """
    email_ok = bool(os.environ.get("EMAIL_PASSWORD"))
    wa_ok = _whatsapp_paired()
    signed_in = _mrcall_signed_in()

    lines = [
        "[CHANNEL AVAILABILITY — live. Only OFFER a channel marked ready. For "
        "one that is NOT ready, tell the user how to enable it instead of "
        "offering to send through it.]",
        f"- Email: {'ready' if email_ok else 'NOT configured (set email in Settings)'}",
        f"- WhatsApp: {'ready' if wa_ok else 'NOT connected (pair it / scan QR in Settings)'}",
        f"- SMS: {'ready (via MrCall credits)' if signed_in else 'NOT available (sign in to MrCall)'}",
        f"- Phone calls (MrCall): {'ready' if signed_in else 'NOT available (sign in to MrCall)'}",
    ]
    return "\n".join(lines)


__all__ = ["get_channel_status_block"]
