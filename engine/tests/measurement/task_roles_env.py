"""Shared capture environment for the task-role measurement harnesses.

The ``TASK_DETECTION``, ``REANALYZE`` and ``DEDUP`` harnesses
(``tests/fixtures/measurement/<ROLE>/capture.py``) replay synthetic cases
through the engine's own worker code and record the request each worker
hands to its LLM client. A measurement run later sends that exact request
to several models and scores the answers against the case labels, so the
capture must be the engine's request and nothing else. This module owns
what the three harnesses share:

- :func:`disposable_profile` — a throwaway profile directory and SQLite
  database booted through the real ``init_db``. The process environment,
  the storage singletons and the settings fields the workers read are
  restored on exit, and personal or credential values exported by the
  caller's shell never reach a synthetic prompt.
- :func:`frozen_clock` — pins the wall clock the request builders read.
  Dates are part of the measured request (``Date:``, ``Today's date``,
  "N days ago"), and the measurement caches results by request hash, so
  a case must render byte-identically on any day.
- :class:`CapturingClient` and :func:`capturing_llm` — stand in for the
  LLM client: every ``create_message`` / ``create_message_sync`` call is
  recorded with its arguments as sent, the active ``call_site`` tag and
  the model the role routed to, and answered with a text-only response,
  the shape every task worker treats as "no decision" without writing.
- seeding helpers for the trained task prompt, emails and open tasks.
- loaders of the committed cases, the profile owners and a role's
  ``capture.py`` / ``score.py`` (by path, as the measurement scripts load
  them).

No network, no key, no paid call: the client is never real.
"""

from __future__ import annotations

import copy
import importlib
import importlib.util
import inspect
import json
import os
import shutil
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "measurement"

# One owner per disposable profile; it never appears in a request.
OWNER_ID = "measurement-owner"

# The routed model each role key resolves to inside a capture. A capture
# whose client was built for another key came from another role's code.
ROLE_KEYS = ("MODEL_TASK_DETECTION", "MODEL_REANALYZE", "MODEL_DEDUP")


def routed_sentinel(role_key: str) -> str:
    """The model name ``routed_model(role_key)`` resolves to in a capture."""
    return "capture-" + role_key.removeprefix("MODEL_").lower()


# Values a shell may export that the prompt builders read from the
# environment (personal-data section, user identity, aliases). They are
# removed for the capture and only the case profile's values are set.
_PERSONAL_KEYS = (
    "EMAIL_ADDRESS",
    "EMAIL_ALIASES",
    "USER_FULL_NAME",
    "USER_PHONE",
    "USER_CODICE_FISCALE",
    "USER_DATE_OF_BIRTH",
    "USER_ADDRESS",
    "USER_IBAN",
    "USER_COMPANY",
    "USER_VAT_NUMBER",
    "USER_SECRET_INSTRUCTIONS",
)
# Removed as well, so nothing in a capture could build a paying client.
_CREDENTIAL_KEYS = ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "LLM_PROVIDER")

_NO_DECISION = "(measurement capture: no decision)"


class CaptureError(RuntimeError):
    """A case did not produce exactly the one request its role makes."""


def load_cases(role: str) -> dict[str, Any]:
    """The committed case document of ``role``."""
    return json.loads((FIXTURES / role / "cases.json").read_text(encoding="utf-8"))


def fixture_module(role: str, name: str):
    """Import ``<ROLE>/<name>.py`` (``capture``, ``score``) by path, as the scripts do."""
    path = FIXTURES / role / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"measurement_{name}_{role.lower()}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_profiles() -> dict[str, dict[str, Any]]:
    """The synthetic profile owners shared by TASK_DETECTION and REANALYZE.

    Both roles send the profile's trained task prompt (agent type
    ``task_email``) as their system prompt in production, so the profiles
    live once, beside the TASK_DETECTION cases: ``environment`` is the
    owner's identity as the engine reads it, ``trained_prompt_file`` the
    prompt the trainer would have stored for that owner.
    """
    base = FIXTURES / "TASK_DETECTION"
    document = json.loads((base / "profiles.json").read_text(encoding="utf-8"))
    profiles = document["profiles"]
    for profile in profiles.values():
        path = base / profile["trained_prompt_file"]
        profile["trained_prompt"] = path.read_text(encoding="utf-8")
    return profiles


def parse_instant(value: str) -> datetime:
    """An ISO-8601 instant from a case (``Z`` allowed) as an aware UTC datetime."""
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        raise ValueError(f"case instants carry a timezone: {value!r}")
    return moment.astimezone(UTC)


def naive_utc(value: str) -> datetime:
    """The naive-UTC form the profile database stores datetimes in."""
    return parse_instant(value).replace(tzinfo=None)


@contextmanager
def disposable_profile(personal: dict[str, str] | None = None) -> Iterator[Path]:
    """Boot a fresh profile and database; restore everything on exit.

    ``personal`` is the profile owner's identity as the running engine
    sees it in its environment (``EMAIL_ADDRESS``, ``USER_FULL_NAME``,
    ``USER_COMPANY``). The profile ``.env`` routes every task role key to
    its :func:`routed_sentinel`, so model policy never consults the
    resolved table. The storage singletons are disposed on entry and on
    exit: call from synchronous code that holds no open engine.
    """
    from zylch.config import settings
    from zylch.storage import database

    saved_env = dict(os.environ)
    saved_settings = (settings.email_address, settings.email_aliases)
    root = Path(tempfile.mkdtemp(prefix="mrcall-measure-"))
    try:
        (root / ".env").write_text(
            "".join(f"{key}={routed_sentinel(key)}\n" for key in ROLE_KEYS),
            encoding="utf-8",
        )
        for key in _PERSONAL_KEYS + _CREDENTIAL_KEYS:
            os.environ.pop(key, None)
        os.environ.update(
            {
                "ZYLCH_PROFILE_DIR": str(root),
                "ZYLCH_DB_PATH": str(root / "zylch.db"),
                "ZYLCH_HOME": str(root / "home"),
                "MEMORY_DB_DIR": str(root / "memory"),
                "MEMORY_KEY": "",
                "OWNER_ID": OWNER_ID,
                **(personal or {}),
            }
        )
        settings.email_address = os.environ.get("EMAIL_ADDRESS", "")
        settings.email_aliases = ""
        database.dispose_engine()
        database.init_db()
        yield root
    finally:
        database.dispose_engine()
        os.environ.clear()
        os.environ.update(saved_env)
        settings.email_address, settings.email_aliases = saved_settings
        shutil.rmtree(root, ignore_errors=True)


class _FrozenMeta(type):
    """Keep ``isinstance(x, datetime)`` true for real datetimes in patched modules."""

    def __instancecheck__(cls, obj: Any) -> bool:
        return isinstance(obj, datetime)


@contextmanager
def frozen_clock(instant: datetime, modules: Sequence[str]) -> Iterator[datetime]:
    """Pin ``datetime.now`` / ``utcnow`` in ``modules`` to ``instant``.

    Each module must import ``datetime`` from :mod:`datetime` at module
    level; a module that stops doing so raises here, so a refactor that
    would let the real clock into a capture is noticed, not absorbed.
    ``now()`` without a timezone answers in naive UTC, so the capture is
    the same on any machine.
    """
    moment = instant.astimezone(UTC)

    class FrozenDatetime(datetime, metaclass=_FrozenMeta):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz) if tz is not None else moment.replace(tzinfo=None)

        @classmethod
        def utcnow(cls):
            return moment.replace(tzinfo=None)

    with ExitStack() as stack:
        for name in modules:
            module = importlib.import_module(name)
            if getattr(module, "datetime", None) is not datetime:
                raise CaptureError(f"{name} no longer imports datetime.datetime; re-pin its clock")
            stack.enter_context(mock.patch.object(module, "datetime", FrozenDatetime))
        yield moment


class CapturingClient:
    """The LLM client of a capture: records each call, answers "no decision"."""

    def __init__(self, routed: str) -> None:
        self.model = routed
        self.calls: list[dict[str, Any]] = []

    async def create_message(self, *args: Any, **kwargs: Any) -> SimpleNamespace:
        return self._record("create_message", args, kwargs)

    def create_message_sync(self, *args: Any, **kwargs: Any) -> SimpleNamespace:
        return self._record("create_message_sync", args, kwargs)

    def _record(self, method: str, args: tuple, kwargs: dict) -> SimpleNamespace:
        from zylch.llm.client import LLMClient
        from zylch.llm.usage import current_call_site

        # Bind against the real client's signature so a positional argument
        # is recorded under its name; defaults the caller did not pass are
        # not part of the request it built and are not recorded.
        bound = inspect.signature(getattr(LLMClient, method)).bind(self, *args, **kwargs)
        sent = {k: v for k, v in bound.arguments.items() if k not in ("self", "kwargs")}
        sent.update(bound.arguments.get("kwargs", {}))
        self.calls.append(
            {
                "method": method,
                "call_site": current_call_site(),
                "routed_model": self.model,
                "request": copy.deepcopy(sent),
            }
        )
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=_NO_DECISION)],
            stop_reason="end_turn",
            usage={"input_tokens": 0, "output_tokens": 0},
            model=self.model,
        )


@contextmanager
def capturing_llm(extra_targets: Sequence[str] = ()) -> Iterator[CapturingClient]:
    """Route the client factories to one :class:`CapturingClient`.

    ``zylch.llm.make_llm_client`` / ``try_make_llm_client`` cover callers
    that import them at call time; ``extra_targets`` names module globals
    bound at import (``zylch.workers.task_creation.make_llm_client``).
    The model the role asked for is kept on the client (``routed``).
    """
    client = CapturingClient(routed="")

    def factory(model: str | None = None) -> CapturingClient:
        client.model = model or ""
        return client

    with ExitStack() as stack:
        for target in ("zylch.llm.make_llm_client", "zylch.llm.try_make_llm_client"):
            stack.enter_context(mock.patch(target, factory))
        for target in extra_targets:
            stack.enter_context(mock.patch(target, factory))
        yield client


def single_request(case: dict[str, Any], client: CapturingClient, role_key: str) -> dict[str, Any]:
    """The one request ``case`` produced, checked against its call site and role."""
    if len(client.calls) != 1:
        raise CaptureError(f"{case['id']}: {len(client.calls)} LLM calls, expected exactly 1")
    call = client.calls[0]
    if call["call_site"] != case["call_site"]:
        raise CaptureError(
            f"{case['id']}: call site {call['call_site']!r}, expected {case['call_site']!r}"
        )
    if call["routed_model"] != routed_sentinel(role_key):
        raise CaptureError(
            f"{case['id']}: client routed to {call['routed_model']!r}, not {role_key}"
        )
    return {"case_id": case["id"], "call_site": call["call_site"], "request": call["request"]}


def seed_trained_prompt(prompt: str) -> None:
    """Store the profile's trained task prompt (agent type ``task_email``)."""
    from zylch.storage.storage import Storage

    Storage.get_instance().store_agent_prompt(OWNER_ID, "task_email", prompt)


def seed_emails(emails: Sequence[dict[str, Any]]) -> None:
    """Insert a case's emails: ``pending`` ones wait for task detection, the
    others were task-processed when they arrived (they still render in the
    thread history, which reads every email of the thread)."""
    for email in emails:
        seed_email(email, None if email.get("pending") else naive_utc(email["date"]))


def seed_email(email: dict[str, Any], processed_at: datetime | None) -> None:
    """Insert one email row; ``processed_at`` marks it as already task-processed."""
    from zylch.storage.database import get_session
    from zylch.storage.models import Email

    sent = parse_instant(email["date"])
    with get_session() as session:
        session.add(
            Email(
                id=email["id"],
                owner_id=OWNER_ID,
                gmail_id=email["id"],
                thread_id=email["thread_id"],
                from_email=email["from"],
                from_name=email.get("from_name", ""),
                to_email=email.get("to", ""),
                cc_email=email.get("cc", ""),
                subject=email.get("subject", ""),
                date=sent.replace(tzinfo=None),
                date_timestamp=int(sent.timestamp()),
                body_plain=email["body"],
                is_auto_reply=bool(email.get("auto_reply", False)),
                task_processed_at=processed_at,
            )
        )


_TASK_FIELDS = (
    "contact_email",
    "contact_phone",
    "contact_name",
    "title",
    "urgency",
    "reason",
    "suggested_action",
    "channel",
)


def seed_task(task: dict[str, Any]) -> None:
    """Insert one open task row exactly as described (id, dates, sources)."""
    from zylch.storage.database import get_session
    from zylch.storage.models import TaskItem

    with get_session() as session:
        session.add(
            TaskItem(
                id=task["id"],
                owner_id=OWNER_ID,
                event_type=task.get("event_type", "email"),
                event_id=task["event_id"],
                action_required=True,
                created_at=naive_utc(task["created_at"]),
                analyzed_at=naive_utc(task.get("analyzed_at", task["created_at"])),
                sources=task.get("sources", {}),
                **{field: task.get(field) for field in _TASK_FIELDS},
            )
        )
