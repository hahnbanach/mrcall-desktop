"""RPC handlers backing the renderer's "Update" view onboarding flow.

The Update view (``app/src/renderer/src/views/Update.tsx``) shows three
ordered cards:

  1. **Sync** — fetch new email + WhatsApp messages. Always actionable.
  2. **Train** — generate personalised agent prompts. Gated on ≥1 row of
     synced data being present.
  3. **Update** — memory extraction + task detection across the synced
     data. Gated on at least one agent prompt having been trained.

This module backs (1) with ``sync.run`` and the gating in (2)/(3) with
``setup.state``. Training itself lives in ``zylch/rpc/agents.py``
(``agents.train_all``); the full update pipeline lives in
``zylch/rpc/methods.py`` (``update.run``).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)

NotifyFn = Callable[[str, Dict[str, Any]], None]


def _owner_id() -> str:
    """Resolve the active profile's owner_id (mirrors agents.py)."""
    from zylch.cli.utils import get_owner_id

    return get_owner_id()


async def sync_run(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """sync.run({days_back?: int}) -> result dict.

    Fetch new emails (IMAP) and WhatsApp messages, then return. Skips
    memory extraction + task detection — those are the responsibility of
    ``update.run`` (and the Training card of the Update view talks to
    ``agents.train_all`` instead).

    Emits ``sync.progress`` notifications (``{pct, message}``) so the
    renderer can drive a progress bar.

    Return shape::

        {
          "success": True | False,
          "summary": str,             # short human line for the card
          "result": {
              "sync_new": int,
              "wa_messages": int,
              "wa_contacts": int,
              "wa_skipped_reason": Optional[str],
          },
          "errors": [                 # one entry per failed stage
              {"severity": "error"|"warning", "title": str,
               "detail": str, "action": str}
          ],
        }
    """
    from zylch.services.error_messages import humanize_error
    from zylch.services.process_pipeline import run_sync_only

    days_back = int(params.get("days_back", 60) or 60)
    owner_id = _owner_id()
    logger.info(f"[rpc] sync.run owner_id={owner_id} days_back={days_back}")

    email_addr = os.environ.get("EMAIL_ADDRESS", "")
    email_pass = os.environ.get("EMAIL_PASSWORD", "")
    if not email_addr or not email_pass:
        # Surface as a structured error rather than raising — the card
        # renders these inline (consistent with `update.run`).
        return {
            "success": False,
            "summary": "Email not configured.",
            "result": {"sync_new": 0, "wa_messages": 0, "wa_contacts": 0},
            "errors": [
                {
                    "severity": "error",
                    "title": "Email not configured",
                    "detail": "EMAIL_ADDRESS / EMAIL_PASSWORD are missing.",
                    "action": "Open Settings and add your IMAP credentials.",
                }
            ],
        }

    def _emit(pct: int, message: str, _eta: Optional[str] = None) -> None:
        try:
            notify("sync.progress", {"pct": int(pct), "message": str(message)})
        except Exception as e:
            logger.debug(f"[sync.run] notify failed (non-fatal): {e}")

    stage_errors: list = []
    try:
        result = await run_sync_only(
            owner_id,
            days_back=days_back,
            progress=_emit,
            errors_out=stage_errors,
        )
    except Exception as e:
        # Last-resort guard: run_sync_only already routes per-stage
        # failures into stage_errors, so this branch only fires if the
        # function itself blew up before reaching its try blocks.
        logger.exception("[rpc] sync.run failed")
        stage_errors.append({"stage": "pipeline", "error": e})
        result = {"sync_new": 0, "wa_messages": 0, "wa_contacts": 0}

    humanized = []
    for entry in stage_errors:
        try:
            humanized.append(humanize_error(entry["error"], entry.get("stage", "")))
        except Exception as e:
            logger.warning(f"[sync.run] humanize_error failed: {e}")

    # The run failed only if a *fatal* stage failed (email_sync). WhatsApp
    # failures degrade to a warning and don't flip success — same policy
    # as update.run.
    fatal = any(h.get("severity") != "warning" for h in humanized)
    success = not fatal

    sync_new = int(result.get("sync_new", 0))
    wa_msgs = int(result.get("wa_messages", 0))
    if success:
        bits = []
        if sync_new:
            bits.append(f"{sync_new} new emails")
        if wa_msgs:
            bits.append(f"{wa_msgs} WhatsApp messages")
        skipped = result.get("wa_skipped_reason")
        if skipped and not wa_msgs:
            bits.append(f"WhatsApp skipped ({skipped})")
        summary = ", ".join(bits) if bits else "Up to date (no new messages)."
    else:
        summary = "Sync failed — see error below."

    logger.info(
        f"[rpc] sync.run -> success={success} new_emails={sync_new} "
        f"wa_messages={wa_msgs} errors={len(humanized)}"
    )
    return {
        "success": success,
        "summary": summary,
        "result": result,
        "errors": humanized,
    }


async def setup_state(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """setup.state() -> current onboarding state.

    Read-only snapshot used by the Update view to decide which of the
    three cards (Sync / Train / Update) is selectable. Specifically:

      - ``has_synced``: at least one email OR one WhatsApp message in
        the local DB. Drives the "Train" card's enabled state.
      - ``has_trained``: at least one ``agent_prompts`` row exists.
        Drives the "Update" card's enabled state.

    The decision is per-profile (each profile owns its own SQLite DB),
    so a brand-new profile starts gated even if a sibling profile on
    the same machine is fully set up.

    Return shape::

        {
          "has_synced": bool,
          "has_trained": bool,
          "emails_count": int,
          "whatsapp_messages_count": int,
          "agents_trained": [str, ...],   # e.g. ["memory_message", "task_email"]
        }
    """
    from zylch.storage.storage import Storage

    owner_id = _owner_id()
    store = Storage.get_instance()

    # Email count via the existing stats accessor. The accessor swallows
    # its own DB errors and returns 0 there, so we don't need a wrapping
    # try/except here.
    try:
        stats = store.get_email_stats(owner_id)
        emails_count = int(stats.get("total_emails", 0) or 0)
    except Exception as e:
        logger.warning(f"[setup.state] email stats failed: {e}")
        emails_count = 0

    # WhatsApp message count. Tolerate the table being absent on installs
    # that have never connected WhatsApp (older schema versions).
    try:
        from zylch.storage.database import get_session
        from zylch.storage.models import WhatsAppMessage

        with get_session() as session:
            wa_count = (
                session.query(WhatsAppMessage)
                .filter(WhatsAppMessage.owner_id == owner_id)
                .count()
            )
    except Exception as e:
        logger.warning(f"[setup.state] whatsapp count failed: {e}")
        wa_count = 0

    # Which agent prompts have been trained. The three trainers the GUI
    # exposes are memory_message, task_email, emailer — same set as
    # `agents.train_all`.
    agents_trained: list = []
    for agent in ("memory_message", "task_email", "emailer"):
        try:
            if store.get_agent_prompt(owner_id, agent):
                agents_trained.append(agent)
        except Exception as e:
            logger.warning(f"[setup.state] get_agent_prompt({agent}) failed: {e}")

    has_synced = emails_count > 0 or wa_count > 0
    has_trained = len(agents_trained) > 0

    state = {
        "has_synced": bool(has_synced),
        "has_trained": bool(has_trained),
        "emails_count": int(emails_count),
        "whatsapp_messages_count": int(wa_count),
        "agents_trained": agents_trained,
    }
    logger.debug(f"[rpc] setup.state -> {state}")
    return state


METHODS: Dict[str, Callable[[Dict[str, Any], NotifyFn], Awaitable[Any]]] = {
    "sync.run": sync_run,
    "setup.state": setup_state,
}
