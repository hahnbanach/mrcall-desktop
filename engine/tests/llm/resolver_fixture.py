"""The 2026-10-02 capture and small synthetic catalogues for the resolver v2 tests.

`fixtures/llm/resolver-2026-10-02/` is what the engine's own script read
from OpenRouter on 2026-10-02 at 13:36Z: the catalogue (`models.json`), the
benchmarks (`benchmarks.json`), the endpoints of the 218 catalogue entries
with tools and a 200,000-token context that are no variant and no alias
(`endpoints.json`), and the read time. `sources()` parses it once.

`entry()` and `endpoint()` build synthetic catalogue entries and endpoints
shaped like the real payloads, for the rules no real entry isolates (a
family matched only through a slug or an alias's target, an endpoint
refused for one reason alone). `outcome()` and `measured_all()` build a
synthetic `measured.json` in the format the measurement script writes
(slice S4), since no real measurement exists before the paid run.
"""

from __future__ import annotations

import copy
import hashlib
import json
from functools import lru_cache
from pathlib import Path

from zylch.llm.roles import candidates

ENGINE = Path(__file__).resolve().parents[2]
FIXTURE = ENGINE / "tests" / "fixtures" / "llm" / "resolver-2026-10-02"
ROLES = ENGINE / "zylch" / "llm" / "roles"
READ_AT = "2026-10-02T13:36:42Z"
SONNET, OPUS = "anthropic/claude-sonnet-5.5", "anthropic/claude-opus-5.5"
QWEN, K3 = "qwen/qwen3.8-max-0902", "moonshotai/kimi-k3"
HAIKU = "anthropic/claude-haiku-4.5"
GLM, GROK, SOL = "z-ai/glm-5.3", "x-ai/grok-4.6", "openai/gpt-6.1-sol"
SHA = hashlib.sha256(b"synthetic").hexdigest()


def requirements() -> dict:
    """The committed requirements.json, as a fresh copy."""
    return json.loads((ROLES / "requirements.json").read_text(encoding="utf-8"))


def raw(where: Path = FIXTURE) -> dict:
    """The payloads of a fixture directory as the script reads them."""
    return {
        "catalogue": (where / "models.json").read_bytes(),
        "benchmarks": (where / "benchmarks.json").read_bytes(),
        "endpoints": (where / "endpoints.json").read_bytes(),
        "read_at": (where / "read-at.txt").read_text(encoding="utf-8").strip(),
    }


@lru_cache(maxsize=None)
def _parsed() -> dict:
    payloads = raw()
    catalogue, _ = candidates.payload_list(payloads["catalogue"], "catalogue")
    benchmarks, _ = candidates.payload_list(payloads["benchmarks"], "benchmarks")
    pool = candidates.endpoint_pool(catalogue, requirements()["common"])
    endpoints = candidates.endpoints_by_model(payloads["endpoints"], pool)
    return {
        "catalogue": catalogue,
        "benchmarks": benchmarks,
        "endpoints": endpoints,
        "read_at": payloads["read_at"],
    }


def sources() -> dict:
    """The parsed capture, as a fresh copy a test may change."""
    return copy.deepcopy(_parsed())


def by_id(catalogue: list) -> dict:
    return {e["id"]: e for e in catalogue}


def endpoint(tag: str = "acme", **fields) -> dict:
    """An endpoint shaped like the payload's, admitted under the committed policy
    for an entry priced 1/2 per million unless `fields` change it."""
    base = {
        "tag": tag,
        "status": 0,
        "quantization": "fp8",
        "supported_parameters": ["max_tokens", "tool_choice", "tools"],
        "supports_tool_choice": {"auto": True, "function": True, "none": True, "required": True},
        "pricing": {"prompt": "0.000001", "completion": "0.000002"},
        "context_length": 262144,
    }
    return {**base, **fields}


def entry(model: str = "acme/model-1", **fields) -> dict:
    """A catalogue entry shaped like the payload's that the screen keeps,
    priced 1/2 per million, unless `fields` change it."""
    base = {
        "id": model,
        "canonical_slug": model + "-20260101",
        "context_length": 262144,
        "pricing": {"prompt": "0.000001", "completion": "0.000002"},
        "supported_parameters": ["max_tokens", "tool_choice", "tools"],
        "expiration_date": None,
    }
    return {**base, **fields}


def outcome(passed=(), failed=(), threshold=None, measured_only=False) -> dict:
    """One role's synthetic measurement."""
    results = {m: {"pass": True} for m in passed} | {m: {"pass": False} for m in failed}
    return {
        "threshold": threshold,
        "measured_only": measured_only,
        "results": results,
        "case_set_sha256": SHA,
        "prompt_sha256": SHA,
    }


def measured_all(req: dict) -> dict:
    """A synthetic measurement of every role: maximise roles passed by the
    capture's leaders, satisfice roles at a threshold of 40."""
    leaders = [SONNET, OPUS, QWEN, GLM, GROK, SOL, K3]
    roles = {}
    for role, rule in req["roles"].items():
        roles[role] = outcome(leaders) if rule["rule"] == "maximise" else outcome(threshold=40)
    return {"schema": 1, "roles": roles}
