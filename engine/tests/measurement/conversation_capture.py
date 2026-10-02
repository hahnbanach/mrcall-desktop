"""What the capture harnesses of the agent and smoke roles share.

Milestone 10 measures a role by replaying, on several models, the request the
engine builds for it and scoring each answer against a label. The harnesses in
``tests/fixtures/measurement/<ROLE>/capture.py`` for CHAT, TASK_SOLVE,
COMPACTION, NARRATION, WEB_SEARCH and TRAIN drive the role's own code path for
every case and record what the call site hands the LLM client. This module is
the part they have in common:

- :class:`CapturingClient` stands where ``LLMClient`` stands at the call site.
  It records the arguments of ``create_message`` / ``create_message_sync`` as
  the caller passed them and answers with a short text, so the code path runs
  to its end. No network, no key, no budget ledger: the request is recorded
  before any of the client's own work (admission, the datetime line, the
  transport) would apply, which is what a measurement arm replays through the
  real client.
- :class:`ReplayClient` answers a case's scripted earlier tool rounds itself
  and hands every later call to the client it wraps — the capturing one here,
  a real one when a measurement continues the turn past the captured request.
- :func:`disposable_profile` boots a throwaway profile on real SQLite files
  through ``tests.memory.mnemonic_env.boot``, with the embedder stubbed, the
  case's persona in the environment and its channels marked ready, and undoes
  every change on exit.
- :func:`route_llm` hands the client to the factories a role's code reaches
  and makes ``routed_model`` resolve nothing: the measurement arm chooses the
  model, so a capture never reads model policy or the network.
- :func:`freeze_clock` pins a module's "now" to :data:`CAPTURE_NOW`, and
  :func:`scripted_result` picks a scripted tool's answer for its arguments.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import sys
import tempfile
import types
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, Iterator, List, Optional

import pytest

from tests.memory.mnemonic_env import (
    COMPANY_A,
    OWNER_A,
    BagOfWordsEmbedder,
    boot,
    clear_process_state,
    stub_embedder,
)

PLACEHOLDER_MODEL = "<role model>"
"""The model a capture names wherever the call site passes the client's own.

A real id here would be measured as if it were the arm's; this one is refused
by every transport, so a replay that forgets to set the arm's model fails
loudly instead of measuring the wrong model.
"""

# Every variable the prompt builders read about the user. All are cleared
# before a case's persona is applied, so a developer's shell never leaks into
# a captured prompt and two runs of the same case capture the same bytes.
PERSONA_KEYS = (
    "EMAIL_ADDRESS",
    "EMAIL_PASSWORD",
    "USER_FULL_NAME",
    "USER_PHONE",
    "USER_CODICE_FISCALE",
    "USER_DATE_OF_BIRTH",
    "USER_ADDRESS",
    "USER_IBAN",
    "USER_COMPANY",
    "USER_VAT_NUMBER",
    "USER_SECRET_INSTRUCTIONS",
    "USER_LANGUAGE",
)

# Far enough ahead that no capture ever sees the stand-in session expire.
_SESSION_EXPIRES_MS = 4_102_444_800_000

CAPTURE_NOW = datetime(2026, 10, 5, 9, 30)
"""The moment a capture happens at, wherever a role writes "now" into its request.

A request captured on another day would differ only by its date, and the
prompt hash a measurement keys its cache on would change with it. No case's
label depends on the date.
"""


# ─── Responses ────────────────────────────────────────────────────────


def _response(blocks: List[Any], stop_reason: str):
    try:
        from zylch.llm import LLMResponse
    except ImportError:  # the adapter's own module, if the package stops re-exporting it
        from zylch.llm.response import LLMResponse

    raw = SimpleNamespace(
        content=blocks,
        stop_reason=stop_reason,
        usage={"input_tokens": 0, "output_tokens": 0},
        model=PLACEHOLDER_MODEL,
    )
    return LLMResponse(raw)


def text_response(text: str):
    """A finished answer: the real response adapter over one text block."""
    return _response([SimpleNamespace(type="text", text=text)], "end_turn")


def tool_use_response(name: str, tool_input: Dict[str, Any], tool_use_id: str):
    """One tool call, parsed by the real response adapter as a provider's would be."""
    block = SimpleNamespace(type="tool_use", id=tool_use_id, name=name, input=dict(tool_input))
    return _response([block], "tool_use")


# ─── What was sent ────────────────────────────────────────────────────


def jsonable(value: Any, path: str = "request") -> Any:
    """A JSON-safe copy of ``value``, or a ``TypeError`` naming where it is not.

    Response blocks a loop keeps in its history (the response adapter's
    dataclasses, SDK objects) become the dicts the client would serialize them
    into; anything else that is not JSON is an argument no request carries, and
    the capture refuses it rather than write something a replay cannot send.
    """
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, dict):
        return {str(k): jsonable(v, f"{path}.{k}") for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v, f"{path}[{i}]") for i, v in enumerate(value)]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return jsonable(dataclasses.asdict(value), path)
    if hasattr(value, "model_dump"):
        return jsonable(value.model_dump(), path)
    raise TypeError(f"{path}: a {type(value).__name__} is not part of a JSON request")


def as_sent(args: tuple, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """The arguments a call site passed, by the names ``LLMClient`` gives them.

    Only what the caller passed: a parameter left to its default is not part
    of the request the role builds. The signature is read at call time, so a
    change to the client's parameters cannot misname a positional argument.
    """
    from zylch.llm import LLMClient

    signature = inspect.signature(LLMClient.create_message_sync)
    bound = signature.bind(None, *args, **kwargs)
    sent: Dict[str, Any] = {}
    for name, value in bound.arguments.items():
        parameter = signature.parameters[name]
        if parameter.kind is inspect.Parameter.VAR_KEYWORD:
            sent.update(value)
        elif name != "self":
            sent[name] = value
    return jsonable(sent)


class CapturingClient:
    """The LLM client as a call site sees it, recording instead of sending.

    Each request is copied when it is made: the agent loops keep appending to
    the list they passed, and a reference would record what the loop did after
    the call instead of what it sent.
    """

    transport = "capture"
    is_metered = False

    def __init__(
        self,
        answer: str = "ok",
        model: str = PLACEHOLDER_MODEL,
        script: Iterable[Any] = (),
    ):
        self.model = model
        self.answer = answer
        self.requests: List[Dict[str, Any]] = []
        # Responses to give before the closing text, in order (tests drive a
        # continued turn with these).
        self._script = list(script)

    def create_message_sync(self, *args: Any, **kwargs: Any):
        self.requests.append(as_sent(args, kwargs))
        return self._script.pop(0) if self._script else text_response(self.answer)

    async def create_message(self, *args: Any, **kwargs: Any):
        return self.create_message_sync(*args, **kwargs)


class ReplayClient:
    """Answers a case's scripted tool rounds, then forwards to ``inner``.

    A replayed round stands for a model call the case has already decided —
    the tool call and, through the role's scripted tools, its result — so the
    request ``inner`` receives first is the one at the case's decision point.
    The tool calls and text of every forwarded answer are kept, for scoring a
    turn that continues past it.
    """

    def __init__(self, replay: Iterable[Dict[str, Any]], inner: Any):
        self.inner = inner
        self.model = getattr(inner, "model", PLACEHOLDER_MODEL)
        self.transport = getattr(inner, "transport", "capture")
        self.is_metered = getattr(inner, "is_metered", False)
        self._script = [
            tool_use_response(step["name"], step.get("input") or {}, f"toolu_replay_{i:02d}")
            for i, step in enumerate(replay, 1)
        ]
        self.replayed = 0
        self.calls: List[Dict[str, Any]] = []
        self.last_text = ""

    def _note(self, response: Any) -> Any:
        texts = []
        for block in getattr(response, "content", None) or []:
            kind = getattr(block, "type", None)
            if kind == "tool_use":
                self.calls.append({"name": block.name, "input": dict(block.input or {})})
            elif kind == "text":
                texts.append(getattr(block, "text", "") or "")
        self.last_text = "".join(texts)
        return response

    def create_message_sync(self, *args: Any, **kwargs: Any):
        if self._script:
            self.replayed += 1
            return self._script.pop(0)
        return self._note(self.inner.create_message_sync(*args, **kwargs))

    async def create_message(self, *args: Any, **kwargs: Any):
        if self._script:
            self.replayed += 1
            return self._script.pop(0)
        return self._note(await self.inner.create_message(*args, **kwargs))


def freeze_clock(mp: pytest.MonkeyPatch, module: types.ModuleType) -> None:
    """Make ``module``'s ``datetime.now()`` read :data:`CAPTURE_NOW`."""

    class _CaptureClock(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return cls.fromtimestamp(CAPTURE_NOW.timestamp())
            return cls.fromtimestamp(CAPTURE_NOW.timestamp(), tz)

    mp.setattr(module, "datetime", _CaptureClock)


def route_llm(mp: pytest.MonkeyPatch, client: Any, *modules: types.ModuleType) -> None:
    """Hand ``client`` to every LLM factory the role reaches; resolve no model.

    ``zylch.llm`` covers the call sites that import the factories inside the
    function; ``modules`` are those that bound the names at import.
    """
    import zylch.llm as llm_package

    for module in (llm_package, *modules):
        for name in ("make_llm_client", "try_make_llm_client"):
            if hasattr(module, name):
                mp.setattr(module, name, lambda *a, **k: client)
        if hasattr(module, "routed_model"):
            mp.setattr(module, "routed_model", lambda *a, **k: PLACEHOLDER_MODEL)


# ─── The profile ──────────────────────────────────────────────────────


def owner_id() -> str:
    """The owner the RPC layer acts for — the one every role's storage reads use."""
    from zylch.cli.utils import get_owner_id

    return get_owner_id()


@contextmanager
def disposable_profile(
    profile: Optional[Dict[str, str]] = None,
    channels: Optional[Dict[str, bool]] = None,
) -> Iterator[SimpleNamespace]:
    """A throwaway profile on real databases, gone with every change on exit.

    ``profile`` is the persona: the environment variables the prompt builders
    read (``EMAIL_ADDRESS``, ``USER_FULL_NAME``, ``USER_COMPANY``, …).
    ``channels`` marks email, WhatsApp and the MrCall sign-in ready — all three
    by default, the state of a desktop user who finished setup — through the
    same local signals the chat's channel block reads: an email password, a
    WhatsApp session file, a Firebase session. None of them is real or used.
    """
    ready = {"email": True, "whatsapp": True, "mrcall": True, **(channels or {})}
    persona = {"EMAIL_ADDRESS": f"{OWNER_A}@company.test", **(profile or {})}
    with (
        tempfile.TemporaryDirectory(prefix="measurement-") as tmp,
        pytest.MonkeyPatch.context() as mp,
    ):
        from zylch.auth import session as session_module
        from zylch.memory import reset_shared_engines
        from zylch.storage import database as dbm
        from zylch.storage import storage as storage_module
        from zylch.tools.factory import ToolFactory

        root = Path(tmp)
        embedder = BagOfWordsEmbedder()
        # The embedder is stubbed; a path that still reached fastembed would
        # download a model mid-capture, so importing it fails instead.
        mp.setitem(sys.modules, "fastembed", None)
        stub_embedder(mp, embedder)
        mp.setattr(storage_module, "_embedding_engine", embedder)
        boot(mp, root, OWNER_A, COMPANY_A)
        profile_dir = root / f"profile-{OWNER_A}"
        for key in PERSONA_KEYS:
            mp.delenv(key, raising=False)
        for key, value in persona.items():
            mp.setenv(key, str(value))
        if ready["email"]:
            mp.setenv("EMAIL_PASSWORD", "measurement-placeholder")
        if ready["whatsapp"]:
            (profile_dir / "whatsapp.db").touch()
        signed_in = None
        if ready["mrcall"]:
            signed_in = session_module.FirebaseSession(
                uid=OWNER_A,
                email=persona["EMAIL_ADDRESS"],
                id_token="measurement-placeholder",
                expires_at_ms=_SESSION_EXPIRES_MS,
            )
        mp.setattr(session_module, "_session", signed_in)
        # The factory caches per-process clients and session state on the
        # class; a capture starts from none and leaves the originals behind.
        for name, empty in (
            ("_imap_clients", {}),
            ("_imap_client_keys", {}),
            ("_session_state", None),
            ("_starchat_client", None),
            ("_email_archive", None),
        ):
            mp.setattr(ToolFactory, name, empty)
        reset_shared_engines()
        try:
            yield SimpleNamespace(
                root=root, profile_dir=profile_dir, mp=mp, embedder=embedder, owner=owner_id()
            )
        finally:
            reset_shared_engines()
            dbm.dispose_engine()
            clear_process_state()


# ─── Seeding ──────────────────────────────────────────────────────────


def seed_email(owner: str, email: Dict[str, Any]) -> None:
    """One synced email row, as the IMAP sync leaves it."""
    from zylch.storage.database import get_session
    from zylch.storage.models import Email

    when = datetime.fromisoformat(email["date"])
    with get_session() as session:
        session.add(
            Email(
                owner_id=owner,
                gmail_id=email["id"],
                thread_id=email.get("thread_id") or f"thread-{email['id']}",
                from_email=email["from_email"],
                from_name=email.get("from_name"),
                to_email=email.get("to_email"),
                cc_email=email.get("cc_email"),
                subject=email.get("subject"),
                date=when,
                date_timestamp=int(when.timestamp()),
                body_plain=email.get("body_plain"),
                message_id_header=email.get("message_id"),
                in_reply_to=email.get("in_reply_to"),
            )
        )


def seed_whatsapp(owner: str, message: Dict[str, Any]) -> None:
    """One synced 1-on-1 WhatsApp message."""
    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppMessage

    with get_session() as session:
        session.add(
            WhatsAppMessage(
                owner_id=owner,
                message_id=message["id"],
                chat_jid=message["chat_jid"],
                sender_jid=message.get("sender_jid") or message["chat_jid"],
                sender_name=message.get("sender_name"),
                text=message["text"],
                timestamp=datetime.fromisoformat(message["timestamp"]),
                is_from_me=bool(message.get("is_from_me")),
                is_group=False,
            )
        )


def seed_blob(embedder: Any, owner: str, content: str, namespace: Optional[str] = None) -> str:
    """One memory blob through the test seeding door; the company family by default."""
    from zylch.memory.blob_storage import BlobStorage
    from zylch.storage.database import get_session

    from tests.memory import seeding

    storage = BlobStorage(get_session, embedder)
    blob = seeding.store_blob(
        storage,
        owner_id=owner,
        namespace=namespace or f"user:{COMPANY_A}",
        content=content,
        event_description="measurement case",
    )
    return blob["id"]


# ─── Cases ────────────────────────────────────────────────────────────


def scripted_result(spec: Any, args: Dict[str, Any]) -> Any:
    """A tool's scripted answer to ``args``.

    Usually the answer itself. A tool whose answer depends on an argument
    (the category of ``get_facts_by_category``) is scripted as
    ``{"by_arg": <argument>, "results": {<value>: <answer>}, "default": …}``,
    the value compared trimmed and case-insensitively.
    """
    if isinstance(spec, dict) and "by_arg" in spec:
        wanted = str(args.get(spec["by_arg"]) or "").strip().lower()
        results = {str(k).strip().lower(): v for k, v in spec["results"].items()}
        return results.get(wanted, spec.get("default"))
    return spec


def load_document(role_dir: Path) -> Dict[str, Any]:
    """A role's ``cases.json``."""
    return json.loads((Path(role_dir) / "cases.json").read_text(encoding="utf-8"))


def case_list(cases: Any) -> List[Dict[str, Any]]:
    """The cases, whether given as the list or as the whole ``cases.json``."""
    if isinstance(cases, dict):
        return list(cases["cases"])
    return list(cases)
