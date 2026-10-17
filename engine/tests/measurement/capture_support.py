"""What every measurement capture harness shares: a throwaway profile and a client that records.

Milestone 10 measures each role by replaying, on several models, the exact request the engine
builds for it (brief D7). A role's ``capture.py`` (``tests/fixtures/measurement/<ROLE>/``)
builds those requests by running the engine's own code path for each case with
:class:`CapturingClient` standing where the real client stands: it keeps the keyword arguments
the call site passes to ``create_message`` / ``create_message_sync`` and answers from a script,
so nothing leaves the process — no network, no key, no paid call.

The profile is throwaway: a temporary directory booted through the memory suites' own helper
(``tests.memory.mnemonic_env.boot`` — a real profile database and company store, the embedder
stubbed) with the role's ``MODEL_<ROLE>`` saved in its ``.env``, so the call site resolves its
model through the role exactly as it does in a real profile. Its provider is OpenRouter with
no OpenRouter key, so a real client cannot be built in it: a call site the harness failed to
reach yields no request and the case is refused, instead of a request reaching a provider.
Every environment change is undone on exit, so a harness runs inside a pytest test or from a
script with ``engine/`` on ``sys.path``, and never reaches a real profile.

It also holds :func:`text_language`, the stated method behind a case's ``expect_lang``.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "measurement"

#: The model a capture routes its role to unless the caller names an arm. A placeholder on
#: purpose: the measurement sends each request on each arm's own model, and a captured request
#: names a model only where the call site itself passes one (``model=`` in its kwargs).
CAPTURE_MODEL = "measurement/capture"


class CaptureError(AssertionError):
    """A case that does not yield exactly one request at its role's call site."""


@dataclass
class Call:
    """One request as the call site made it: the method, the client's model, the kwargs."""

    method: str
    model: str | None
    request: dict[str, Any]


def plain(kwargs: dict[str, Any]) -> dict[str, Any]:
    """The kwargs as JSON would carry them — a request the measurement can store and replay."""
    try:
        return json.loads(json.dumps(kwargs, ensure_ascii=False))
    except (TypeError, ValueError) as e:
        raise CaptureError(f"request is not JSON-serialisable as sent: {e}") from None


class CapturingClient:
    """Stands where ``LLMClient`` stands: records each request, answers from ``answer``.

    ``answer`` receives the recorded request and returns a response shaped as the call sites
    read one (``content`` blocks with ``type``/``name``/``input`` or ``text``), so the code
    path finishes the way it finishes in production.
    """

    def __init__(self, model: str | None, answer: Callable[[dict[str, Any]], Any], calls):
        self.model = model
        self._answer = answer
        self._calls = calls

    async def create_message(self, **kwargs):
        return self._record("create_message", kwargs)

    def create_message_sync(self, **kwargs):
        return self._record("create_message_sync", kwargs)

    def _record(self, method: str, kwargs: dict[str, Any]):
        request = plain(kwargs)
        self._calls.append(Call(method, self.model, request))
        return self._answer(request)


def client_factory(calls: list[Call], answer: Callable[[dict[str, Any]], Any]):
    """A stand-in for ``make_llm_client`` / ``try_make_llm_client`` building recording clients."""

    def make(model: str | None = None) -> CapturingClient:
        return CapturingClient(model, answer, calls)

    return make


def _response(block: SimpleNamespace, stop_reason: str) -> SimpleNamespace:
    return SimpleNamespace(
        content=[block],
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=0, output_tokens=0),
    )


def tool_answer(name: str, payload: dict[str, Any]) -> SimpleNamespace:
    """A response holding one ``tool_use`` block for ``name``."""
    block = SimpleNamespace(type="tool_use", id="toolu_capture", name=name, input=payload)
    return _response(block, "tool_use")


def text_answer(text: str) -> SimpleNamespace:
    """A response holding one ``text`` block."""
    return _response(SimpleNamespace(type="text", text=text), "end_turn")


def tool_names(request: dict[str, Any]) -> list[str]:
    """The names of the tools a request offers, in order."""
    return [str(tool.get("name")) for tool in request.get("tools") or []]


def the_request(
    case_id: str, calls: list[Call], *, model: str, tool: str | None = None
) -> dict[str, Any]:
    """The one request ``case_id`` made at its role's call site.

    With ``tool``, the call site is the request offering that tool (a role may make other
    requests on the same path); without it, the case must have made exactly one request.
    Refused unless exactly one request matches and its client was built for ``model`` — the
    value saved under the role's ``MODEL_<ROLE>``, which proves the call site routed through
    its own role.
    """
    at_site = [call for call in calls if tool is None or tool in tool_names(call.request)]
    if len(at_site) != 1:
        raise CaptureError(
            f"{case_id}: {len(at_site)} request(s) at the call site"
            f"{f' (tool {tool!r})' if tool else ''} out of {len(calls)}; expected exactly one"
        )
    call = at_site[0]
    if call.model != model:
        raise CaptureError(
            f"{case_id}: the call site built its client for {call.model!r}, "
            f"not for the role's saved model {model!r}"
        )
    return call.request


@contextmanager
def disposable_profile(env_key: str, model: str) -> Iterator[SimpleNamespace]:
    """Boot a throwaway profile whose ``.env`` saves ``env_key=model``; undo it all on exit.

    Yields ``owner``, ``company_key``, ``embedder`` (the stub the memory suites share) and
    ``monkeypatch`` (undone on exit, so a harness patches its call site's factory with it).
    """
    from tests.memory.mnemonic_env import (
        COMPANY_A,
        OWNER_A,
        BagOfWordsEmbedder,
        boot,
        clear_process_state,
        stub_embedder,
    )
    from zylch.storage import database as dbm

    # Exits run in reverse: engines disposed, then the environment restored, then the files gone.
    with (
        tempfile.TemporaryDirectory(prefix="measurement-") as root,
        pytest.MonkeyPatch.context() as mp,
    ):
        embedder = BagOfWordsEmbedder()
        stub_embedder(mp, embedder)
        owner = boot(mp, Path(root), OWNER_A, COMPANY_A)
        env_file = Path(os.environ["ZYLCH_PROFILE_DIR"]) / ".env"
        with env_file.open("a", encoding="utf-8") as fh:
            # The provider without its key: no real client can be built (see the docstring).
            fh.write(f"LLM_PROVIDER=openrouter\n{env_key}={model}\n")
        try:
            yield SimpleNamespace(
                owner=owner, company_key=COMPANY_A, embedder=embedder, monkeypatch=mp
            )
        finally:
            dbm.dispose_engine()
            clear_process_state()


def cases_of(cases: Any) -> list[dict[str, Any]]:
    """The case list, given either a whole ``cases.json`` document or its ``cases``."""
    return list(cases["cases"] if isinstance(cases, dict) else cases)


def document_of(cases: Any, role: str) -> dict[str, Any]:
    """The ``cases.json`` document: the one given, else the role's committed file."""
    return cases if isinstance(cases, dict) else load_cases(role)


def load_cases(role: str) -> dict[str, Any]:
    """The role's committed ``cases.json``."""
    return json.loads((FIXTURES / role / "cases.json").read_text(encoding="utf-8"))


def load_authored(role: str) -> dict[str, Any]:
    """The role's authored case set: ``cases.json`` and any trimmed reserve (``case_sets.py``)."""
    from tests.measurement.case_sets import authored_document

    return authored_document(FIXTURES / role)


def load_capture(role: str) -> ModuleType:
    """The role's ``capture.py``, imported by path (the fixture directories are not packages)."""
    path = FIXTURES / role / "capture.py"
    spec = importlib.util.spec_from_file_location(f"measurement_capture_{role.lower()}", path)
    if spec is None or spec.loader is None:
        raise CaptureError(f"no capture harness at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: The function words the language check counts: frequent in one language and rare in the
#: other in short business sentences. Left out on purpose: "a", "in", "per" (words in both);
#: "e" and "all" (fragments of "e-mail" and "all'"); "ai" and "i" ("AI", "I").
_FUNCTION_WORDS = {
    "it": frozenset(
        "il lo la l gli le un una uno di del dell della dello dei degli delle che non con al "
        "alla alle agli dal dall dalla nel nell nella nelle nei negli sull da su si ci lei "
        "loro sono è sempre mai solo ogni dopo prima quando anche questo questa nostro "
        "nostra nostri nostre suo sua".split()
    ),
    "en": frozenset(
        "the of to and is are for with not always never only every after before when also "
        "as their they them be must should any by on at from our your we you it this that".split()
    ),
}


def text_language(text: str) -> str | None:
    """The language a short free text is written in: ``"it"``, ``"en"``, or None if undecided.

    The check behind a case's ``expect_lang``, for answers of one sentence, where a statistical
    detector is unreliable: lowercase the text, split it into words on anything that is not a
    letter (accented letters are letters), count the words found in each language's
    function-word list, and return the language with strictly more hits. A tie, including no
    hit at all, is None, which fails the bar.
    """
    words = re.findall(r"[^\W\d_]+", text.lower())
    hits = {lang: sum(word in vocab for word in words) for lang, vocab in _FUNCTION_WORDS.items()}
    if hits["it"] == hits["en"]:
        return None
    return "it" if hits["it"] > hits["en"] else "en"
