"""What the role-measurement scripts share (milestone 10, brief D7, plan S4b).

``build_measurement_requests.py`` captures each role's requests through its
harness, ``measure_roles.py`` runs every arm on them, ``derive_thresholds.py``
turns the results into ``zylch/llm/roles/measured.json``. This module holds what
all three need: the paths and role groups, the D7 priority order, one role's
capture with its checks, the two hashes, the client's datetime line for a
capture moment, and the request a client would reserve for given arguments.

## ``requests.json`` (one per role, beside its ``cases.json``)

``{"schema": 1, "role", "prompt_sha256", "case_set_sha256", "requests":
[{"case_id", "request", "capture_now"}]}``. ``request`` is what the role's call
site passed to the client, as the harness recorded it; ``capture_now`` is the
moment the case happens at (the harness entry's own ``capture_now``, else the
case input's ``now``, else ``conversation_capture.CAPTURE_NOW``), to which a
replay pins the client's datetime line (label review G5).

## The hashes — exactly what is hashed

- ``case_set_sha256``: SHA-256 of the bytes of the role's ``cases.json`` as
  committed.
- ``prompt_sha256``: SHA-256 of the canonical JSON (``sort_keys``, separators
  ``,`` ``:``, ``ensure_ascii`` false) of the sorted list of the distinct
  request templates of the role. A template is one captured request reduced to
  ``system``, ``messages``, ``tools``, ``tool_choice`` and ``max_tokens`` (the
  ``model`` the replay replaces and the transport's ``cache_control`` hints
  are left out), in which every string of the case's own ``input`` — each
  whole string and each of its lines, stripped, of at least ``MIN_DATA``
  characters, longest first — is replaced by ``PLACEHOLDER``. The messages are
  included because several roles carry the engine's instructions in the user
  turn (INTENT, WEB_SEARCH and TRAIN have no system prompt at all); case data
  the harness renders differently from its input (a reformatted date, a body
  with its quotes stripped) stays in the template, so the hash is complete for
  the prompts and deterministic for the case set, not free of every case
  byte. Replacing the case's strings also normalises the one ordering that
  differs between processes: the TRAIN trainers list contacts and greetings
  from sets, and every listed item is case data, so their templates are the
  same in any order.
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest import mock

ENGINE = Path(__file__).resolve().parents[1]
FIXTURES = ENGINE / "tests" / "fixtures" / "measurement"
ROLES_DIR = ENGINE / "zylch" / "llm" / "roles"
REQUIREMENTS = ROLES_DIR / "requirements.json"
MEASURED = ROLES_DIR / "measured.json"
CORPUS_CASES = ENGINE / "tests" / "fixtures" / "mnemonic" / "incidents.json"

# The roles with a case set and a capture harness under FIXTURES.
DECISION_ROLES = (
    "TASK_DETECTION",
    "REANALYZE",
    "DEDUP",
    "REPLY_NEED",
    "INTENT",
    "CORRECTION_LEARNING",
    "SYNC_ANALYSIS",
)
AGENT_ROLES = ("CHAT", "TASK_SOLVE")
SMOKE_ROLES = ("COMPACTION", "NARRATION", "WEB_SEARCH", "TRAIN")
HARNESS_ROLES = DECISION_ROLES + AGENT_ROLES + SMOKE_ROLES
# Measured by the M9 corpus runner (tests/memory/test_mnemonic_corpus_live.py):
# one run per arm routes all three role keys to the arm.
CORPUS_ROLES = ("MNEMONIC", "MEMORY_EXTRACT", "MEMORY_MERGE")
# Brief D7's order of priority under the cap: MNEMONIC (M9's AC 5, with the
# extraction its corpus runs exercise), the seven decision roles, CHAT and
# TASK_SOLVE, MEMORY_MERGE, the smokes; the reference's second repetition last.
PRIORITY = (
    "MNEMONIC",
    "MEMORY_EXTRACT",
    *DECISION_ROLES,
    *AGENT_ROLES,
    "MEMORY_MERGE",
    *SMOKE_ROLES,
)
# Harnesses that take the whole cases.json document (they read top-level keys
# such as INTENT's `skills`); the task-role harnesses take the case list.
LIST_HARNESSES = ("TASK_DETECTION", "REANALYZE", "DEDUP")

PLACEHOLDER = "\u27e8case\u27e9"
MIN_DATA = 4
TEMPLATE_KEYS = ("system", "messages", "tools", "tool_choice", "max_tokens")


class CaptureRefused(RuntimeError):
    """A harness did not yield exactly one request for every case."""


def importable() -> None:
    """Put ``engine/`` on ``sys.path``: the harnesses import ``zylch`` and ``tests``."""
    if str(ENGINE) not in sys.path:
        sys.path.insert(0, str(ENGINE))


def canonical(value: Any) -> str:
    """The canonical JSON the hashes are taken over."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def cases_path(role: str) -> Path:
    return FIXTURES / role / "cases.json"


def requests_path(role: str) -> Path:
    return FIXTURES / role / "requests.json"


def load_document(role: str) -> dict:
    """The role's committed ``cases.json``."""
    return json.loads(cases_path(role).read_text(encoding="utf-8"))


def case_set_sha256(role: str) -> str:
    """SHA-256 of the bytes of the role's committed ``cases.json``."""
    return sha256_hex(cases_path(role).read_bytes())


def load_requests(role: str) -> dict:
    """The role's committed ``requests.json``."""
    return json.loads(requests_path(role).read_text(encoding="utf-8"))


def load_harness(role: str, directory: Path | None = None):
    """``<ROLE>/capture.py`` imported by path (the fixture directories are not packages)."""
    importable()
    path = (directory or FIXTURES / role) / "capture.py"
    spec = importlib.util.spec_from_file_location(f"measurement_harness_{role.lower()}", path)
    if spec is None or spec.loader is None:
        raise CaptureRefused(f"{role}: no capture harness at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def default_capture_now() -> str:
    """The moment every capture without its own happens at (``CAPTURE_NOW``)."""
    importable()
    from tests.measurement.conversation_capture import CAPTURE_NOW

    return CAPTURE_NOW.isoformat()


def capture(role: str, document: dict, harness=None) -> list[dict]:
    """Run the role's harness on ``document``; one entry per case, in case order.

    Refused (``CaptureRefused``) when a case yields no request or more than
    one: the entries must name every case once, in order, and a harness that
    counts the requests reaching its client (``calls=``) must count one for
    every case — those harnesses would otherwise keep the last of several.
    """
    harness = harness or load_harness(role)
    cases = document["cases"]
    counts: dict[str, int] = {}
    kwargs = (
        {"calls": counts} if "calls" in inspect.signature(harness.build_requests).parameters else {}
    )
    given = cases if role in LIST_HARNESSES else document
    entries = harness.build_requests(given, **kwargs)
    expected = [case["id"] for case in cases]
    got = [entry.get("case_id") for entry in entries]
    if got != expected:
        raise CaptureRefused(
            f"{role}: requests for {got}, expected exactly one per case {expected}"
        )
    for case_id, count in counts.items():
        if count != 1:
            raise CaptureRefused(f"{role}/{case_id}: {count} requests reached the client, not 1")
    fallback = default_capture_now()
    out = []
    for case, entry in zip(cases, entries):
        request = entry.get("request")
        if not isinstance(request, dict) or not request.get("messages"):
            raise CaptureRefused(f"{role}/{case['id']}: the harness returned no request")
        now = entry.get("capture_now") or case["input"].get("now") or fallback
        row = {"case_id": case["id"], "request": request, "capture_now": now}
        if entry.get("call_site"):
            row["call_site"] = entry["call_site"]
        out.append(row)
    return out


def case_strings(value: Any, found: set[str] | None = None) -> set[str]:
    """Every string of a case input, and every line of one, stripped, of MIN_DATA+ chars."""
    found = set() if found is None else found
    if isinstance(value, str):
        for piece in (value, *value.splitlines()):
            piece = piece.strip()
            if len(piece) >= MIN_DATA:
                found.add(piece)
    elif isinstance(value, dict):
        for item in value.values():
            case_strings(item, found)
    elif isinstance(value, list):
        for item in value:
            case_strings(item, found)
    return found


def template(value: Any, data: list[str]) -> Any:
    """``value`` without ``cache_control`` hints, each string of ``data`` replaced."""
    if isinstance(value, str):
        for piece in data:
            if piece in value:
                value = value.replace(piece, PLACEHOLDER)
        return value
    if isinstance(value, dict):
        return {k: template(v, data) for k, v in value.items() if k != "cache_control"}
    if isinstance(value, list):
        return [template(item, data) for item in value]
    return value


def request_template(request: dict, case: dict) -> str:
    """One captured request as the canonical JSON of its template (see the module docstring)."""
    data = sorted(case_strings(case["input"]), key=lambda piece: (-len(piece), piece))
    kept = {key: request[key] for key in TEMPLATE_KEYS if key in request}
    return canonical(template(kept, data))


def prompt_sha256(entries: list[dict], cases: list[dict]) -> str:
    """The role's prompt hash over its captured requests (see the module docstring)."""
    by_id = {case["id"]: case for case in cases}
    templates = {request_template(entry["request"], by_id[entry["case_id"]]) for entry in entries}
    return sha256_hex(canonical(sorted(templates)))


def requests_document(role: str, document: dict, entries: list[dict], cases_bytes: bytes) -> dict:
    """The ``requests.json`` document of a capture."""
    return {
        "schema": 1,
        "role": role,
        "prompt_sha256": prompt_sha256(entries, document["cases"]),
        "case_set_sha256": sha256_hex(cases_bytes),
        "requests": entries,
    }


def dump(document: dict) -> str:
    return json.dumps(document, ensure_ascii=False, indent=1) + "\n"


def datetime_line(capture_now: str) -> str:
    """The client's datetime line at ``capture_now``, through the client's own formatter.

    An aware instant is rendered in the machine's time zone, as the client
    renders the real moment; a naive one is local wall time, as
    ``conversation_capture.freeze_clock`` pins a harness's clock.
    """
    importable()
    from zylch.llm import client as client_module

    moment = datetime.fromisoformat(capture_now)
    local = moment.astimezone()

    class Pinned(datetime):
        @classmethod
        def now(cls, tz=None):
            return local.astimezone(tz) if tz is not None else local.replace(tzinfo=None)

    with mock.patch.object(client_module, "datetime", Pinned):
        return client_module.current_datetime_line()


class _Reserved(Exception):
    def __init__(self, request: dict):
        super().__init__("reserved")
        self.request = request


def reserved_request(client: Any, **kwargs: Any) -> dict:
    """The dict ``client`` would reserve and send for ``kwargs``; nothing is reserved or sent.

    The client's own code builds it — the datetime line, the one shape,
    K3's adapter controls — up to the reservation, which raises with the dict
    instead. Preparation's dispatch check is skipped: it counts attempts inside
    a run, and computing a bound is not one. Not thread-safe (it patches two
    module attributes for the call); compute bounds before any parallel work.
    """
    from zylch.llm import budget
    from zylch.services import preparation

    def stop(request_kwargs, transport, *, quote=None):
        raise _Reserved(request_kwargs)

    with (
        mock.patch.object(budget, "reserve", stop),
        mock.patch.object(preparation, "check_dispatch", lambda **_kwargs: None),
    ):
        try:
            client.create_message_sync(**kwargs)
        except _Reserved as reserved:
            return reserved.request
    raise RuntimeError("the client returned without reserving")


def latest_rows(rows: list[dict]) -> list[dict]:
    """One row per (role, arm, case, repetition): the last one written.

    A cell that never reached a provider (unpriced, skipped, stopped at the
    cap) runs again when a run is resumed; its newer row supersedes the old.
    """
    latest: dict[tuple, dict] = {}
    for row in rows:
        key = (row["role"], row["arm"], row["case_id"], row.get("repetition", 1))
        latest.pop(key, None)
        latest[key] = row
    return list(latest.values())


def requirements() -> dict:
    return json.loads(REQUIREMENTS.read_text(encoding="utf-8"))


def reference_model() -> str:
    """The measurement's reference (``requirements.json``: K3 at max effort, the production model)."""
    return requirements()["reference"]


def load_arms(path: Path) -> dict:
    """The bootstrap arms (``resolve_models.py --bootstrap``), the reference in every role.

    Returns ``{role: [{"id", "score", "index", "reference"}]}`` with the
    reference first, so a role cut short by the cap still has its yardstick.
    """
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("schema") != 1 or not isinstance(document.get("roles"), dict):
        raise ValueError(f"{path}: not the bootstrap arms of resolve_models.py --bootstrap")
    reference = document.get("reference") or reference_model()
    out = {}
    for role, body in document["roles"].items():
        index = body["index"]
        arms = [
            {"id": arm["id"], "score": arm.get("score"), "index": index, "reference": False}
            for arm in body["arms"]
            if arm["id"] != reference
        ]
        own = next((arm for arm in body["arms"] if arm["id"] == reference), {})
        out[role] = [
            {"id": reference, "score": own.get("score"), "index": index, "reference": True},
            *arms,
        ]
    return out
