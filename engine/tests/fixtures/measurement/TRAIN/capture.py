"""Capture harness for TRAIN: the meta-prompt request of each case's trainer.

Builders (``input.builder`` names one), the three trainers the desktop's
"Train all" runs (``zylch.rpc.agents.agents_train_all``):

- ``…memory_message.MessageMemoryAgentTrainer.build_memory_message_prompt`` —
  the entity-extraction prompt, from recent email threads and the 1-on-1
  WhatsApp chats the user replied in;
- ``…task_email.EmailTaskAgentTrainer.build_task_prompt`` — the task-detection
  prompt, from recent threads and the memory blobs of their contacts;
- ``…emailer.EmailerAgentTrainer.build_emailer_prompt`` — the email-writing
  prompt, from the user's sent emails.

Each makes one ``create_message`` call with its meta-prompt as the only user
turn and ``max_tokens`` 4000. The harness seeds what the trainer reads —
``input.emails``, ``input.whatsapp`` and ``input.memory`` (company memory
blobs) — under the owner the RPC uses, then runs the builder.
"""

from __future__ import annotations

import asyncio
import importlib
import os
from typing import Any, Dict, List, Optional

from tests.measurement import conversation_capture as cc

ROLE = "TRAIN"


def _builder(path: str):
    module_path, class_name, method_name = path.rsplit(".", 2)
    return getattr(importlib.import_module(module_path), class_name), method_name


def run_case(case: Dict[str, Any], client: Any) -> Any:
    """Run the case's trainer with ``client``; return what its builder returns."""
    from zylch.agents.trainers import base, memory_message, task_email
    from zylch.storage.storage import Storage

    given = case["input"]
    trainer_class, method = _builder(given["builder"])
    with cc.disposable_profile(given.get("profile")) as profile:
        cc.route_llm(profile.mp, client, base, memory_message, task_email)
        profile.mp.setattr(task_email, "EmbeddingEngine", lambda *_a, **_k: profile.embedder)
        for email in given.get("emails") or []:
            cc.seed_email(profile.owner, email)
        for message in given.get("whatsapp") or []:
            cc.seed_whatsapp(profile.owner, message)
        for content in given.get("memory") or []:
            cc.seed_blob(profile.embedder, profile.owner, content)
        trainer = trainer_class(Storage(), profile.owner, os.environ["EMAIL_ADDRESS"])
        return asyncio.run(getattr(trainer, method)())


def build_requests(cases: Any, *, calls: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """The trainer's meta-prompt request for each case, as the trainer passed it."""
    captured = []
    for case in cc.case_list(cases):
        client = cc.CapturingClient(answer="Generated prompt.")
        prompt, _metadata = run_case(case, client)
        if not prompt.startswith(client.answer):
            raise RuntimeError(f"{case['id']}: the trainer did not finish: {prompt!r}")
        if calls is not None:
            calls[case["id"]] = len(client.requests)
        captured.append({"case_id": case["id"], "request": client.requests[-1]})
    return captured
