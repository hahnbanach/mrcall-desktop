"""RPC handlers for agent training — the "Train assistant" button.

A single ``agents.train_all`` method runs the three real trainers serially
and emits ``agents.train.progress`` notifications so the renderer can show
a progress bar. Trainer reference:

  - ``memory_message`` (channel-aware: email + WhatsApp samples)
      → ``MessageMemoryAgentTrainer.build_memory_message_prompt``
  - ``task_email`` (task detection from email threads + blobs)
      → ``EmailTaskAgentTrainer.build_task_prompt``
  - ``emailer`` (writing style from sent emails)
      → ``EmailerAgentTrainer.build_emailer_prompt``

Each step writes the resulting prompt to ``agent_prompts`` so the workers
on the next ``update.run`` pick it up via ``get_agent_prompt``.

Engine-side counterpart of the desktop's "Train assistant" card in
``app/src/renderer/src/views/Update.tsx``.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Awaitable, Callable, Dict

logger = logging.getLogger(__name__)

NotifyFn = Callable[[str, Dict[str, Any]], None]


def _owner_id() -> str:
    """Resolve the active profile's owner_id (same convention as the rest
    of the dispatcher — see ``cli.utils.get_owner_id``)."""
    from zylch.cli.utils import get_owner_id

    return get_owner_id()


def _emit_progress(
    notify: NotifyFn,
    *,
    pct: int,
    step: int,
    total: int,
    current: str,
    message: str,
) -> None:
    """Wrapper to keep the notification shape consistent across steps."""
    payload = {
        "pct": pct,
        "step": step,
        "total": total,
        "current": current,
        "message": message,
    }
    try:
        notify("agents.train.progress", payload)
    except Exception as e:
        logger.debug(f"[agents.train_all] notify failed (non-fatal): {e}")


async def agents_train_all(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """agents.train_all() -> {ok, results}.

    Run all three personalised-agent trainers serially. Emits
    ``agents.train.progress`` notifications between steps so the renderer
    can drive a progress bar.

    Returns:
        {
          "ok": bool,
          "results": {
            "memory_message": {ok, threads_analyzed, whatsapp_chats_analyzed} | {ok: false, error},
            "task_email":     {ok, threads_analyzed}                         | {ok: false, error},
            "emailer":        {ok}                                           | {ok: false, error},
          }
        }
    """
    from zylch.agents.trainers import (
        EmailerAgentTrainer,
        EmailTaskAgentTrainer,
        MessageMemoryAgentTrainer,
    )
    from zylch.llm import try_make_llm_client
    from zylch.storage import Storage

    owner_id = _owner_id()
    user_email = os.environ.get("EMAIL_ADDRESS", "")
    logger.info(f"[rpc] agents.train_all owner_id={owner_id} user_email={user_email}")

    if try_make_llm_client() is None:
        msg = (
            "No LLM configured. Set ANTHROPIC_API_KEY in the profile .env "
            "or sign in with Firebase to use MrCall credits."
        )
        _emit_progress(notify, pct=0, step=0, total=3, current="", message=msg)
        return {"ok": False, "error": msg, "results": {}}

    store = Storage()
    results: Dict[str, Any] = {}
    total = 3
    overall_ok = True

    # ─── Step 1/3 — memory_message ──────────────────────────────
    _emit_progress(
        notify,
        pct=5,
        step=1,
        total=total,
        current="memory_message",
        message="Training memory agent (email + WhatsApp)…",
    )
    try:
        trainer = MessageMemoryAgentTrainer(store, owner_id, user_email)
        prompt, metadata = await trainer.build_memory_message_prompt()
        if not prompt or not prompt.strip():
            raise RuntimeError("memory training produced an empty prompt")
        store.store_agent_prompt(owner_id, "memory_message", prompt, metadata)
        results["memory_message"] = {
            "ok": True,
            "threads_analyzed": metadata.get("threads_analyzed", 0),
            "whatsapp_chats_analyzed": metadata.get("whatsapp_chats_analyzed", 0),
        }
        _emit_progress(
            notify,
            pct=33,
            step=1,
            total=total,
            current="memory_message",
            message=(
                f"Memory agent trained "
                f"({metadata.get('threads_analyzed', 0)} email threads, "
                f"{metadata.get('whatsapp_chats_analyzed', 0)} WhatsApp chats)."
            ),
        )
    except Exception as e:
        logger.exception(f"[agents.train_all] memory_message failed: {e}")
        overall_ok = False
        results["memory_message"] = {"ok": False, "error": str(e)}
        _emit_progress(
            notify,
            pct=33,
            step=1,
            total=total,
            current="memory_message",
            message=f"Memory agent training failed: {e}",
        )

    # ─── Step 2/3 — task_email ──────────────────────────────────
    _emit_progress(
        notify,
        pct=40,
        step=2,
        total=total,
        current="task_email",
        message="Training task-detection agent…",
    )
    try:
        trainer = EmailTaskAgentTrainer(store, owner_id, user_email)
        prompt, metadata = await trainer.build_task_prompt()
        if not prompt or not prompt.strip():
            raise RuntimeError("task training produced an empty prompt")
        store.store_agent_prompt(owner_id, "task_email", prompt, metadata)
        results["task_email"] = {
            "ok": True,
            "threads_analyzed": metadata.get("threads_analyzed", 0),
        }
        _emit_progress(
            notify,
            pct=66,
            step=2,
            total=total,
            current="task_email",
            message=(f"Task agent trained " f"({metadata.get('threads_analyzed', 0)} threads)."),
        )
    except Exception as e:
        logger.exception(f"[agents.train_all] task_email failed: {e}")
        overall_ok = False
        results["task_email"] = {"ok": False, "error": str(e)}
        _emit_progress(
            notify,
            pct=66,
            step=2,
            total=total,
            current="task_email",
            message=f"Task agent training failed: {e}",
        )

    # ─── Step 3/3 — emailer ─────────────────────────────────────
    _emit_progress(
        notify,
        pct=72,
        step=3,
        total=total,
        current="emailer",
        message="Training email-writing agent (your style)…",
    )
    try:
        trainer = EmailerAgentTrainer(store, owner_id, user_email)
        prompt, metadata = await trainer.build_emailer_prompt()
        if not prompt or not prompt.strip():
            raise RuntimeError("emailer training produced an empty prompt")
        store.store_agent_prompt(owner_id, "emailer", prompt, metadata)
        results["emailer"] = {"ok": True}
        _emit_progress(
            notify,
            pct=100,
            step=3,
            total=total,
            current="emailer",
            message="Email-writing agent trained.",
        )
    except Exception as e:
        logger.exception(f"[agents.train_all] emailer failed: {e}")
        overall_ok = False
        results["emailer"] = {"ok": False, "error": str(e)}
        _emit_progress(
            notify,
            pct=100,
            step=3,
            total=total,
            current="emailer",
            message=f"Email-writing agent training failed: {e}",
        )

    logger.info(f"[rpc] agents.train_all -> ok={overall_ok} results={results}")
    return {"ok": overall_ok, "results": results}


METHODS: Dict[str, Callable[[Dict[str, Any], NotifyFn], Awaitable[Any]]] = {
    "agents.train_all": agents_train_all,
}
