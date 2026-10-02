"""The corpus runner's provider plumbing (milestone 10, plan S4b): which provider, key and arm.

Milestone 9 ran the priced corpus on Anthropic's direct transport with
``claude-haiku-4-5`` fixed in code; the CTO rejected that arm (brief, "Why"),
and milestone 10 measures ``MNEMONIC``, ``MEMORY_EXTRACT`` and
``MEMORY_MERGE`` on the measurement's arms through OpenRouter (10b's runner
work, absorbed into D7). Everything of the bench that depends on the
provider lives here, so ``corpus_live_env.py`` stays a provider-free bench:

- :class:`Arm` — the provider (``MNEMONIC_CORPUS_PROVIDER``: ``openrouter``
  by default, or ``anthropic``), its transport, the name of its secret
  (``OPENROUTER_API_KEY`` / ``ANTHROPIC_API_KEY``), the model, and the
  refusal the transport gives a model it cannot price.
- :func:`arm_from` — the arm comes from the measurement's arms, never from a
  model typed on a command line: ``MNEMONIC_CORPUS_ARMS`` names the file
  ``resolve_models.py --bootstrap`` wrote, ``MNEMONIC_CORPUS_ARM`` one of its
  arms of ``MNEMONIC``, ``MEMORY_EXTRACT`` or ``MEMORY_MERGE`` (on the
  ``anthropic`` provider the arm's direct id runs). A live run without them
  is refused; a dry run without them runs the reference
  (``requirements.json``), the production model.
- :func:`scripted_client` and :func:`text_response` — the real ``LLMClient``
  of the arm's transport with only the wire scripted, each response carrying
  the receipt that transport settles from (OpenRouter's ``usage.cost``).
- :func:`bound` — the reservation the engine takes on the arm's transport for
  a request: the dict the client would send (the one shape, the datetime
  line, K3's adapter controls), priced by ``budget_pricing.request_bound``.
- :func:`decision_request` / :func:`extraction_request` — the requests whose
  bounds the runner admits; ``measure_roles.py --project`` prices them too.

The profile runs all three role keys on the arm (``MODEL_MNEMONIC``,
``MODEL_MEMORY_EXTRACT``, ``MODEL_MEMORY_MERGE``), so one run measures the
interactive decisions, the extraction and the automatic decisions the
worker routes through ``MODEL_MEMORY_MERGE``.
"""

from __future__ import annotations

import functools
import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping
from unittest.mock import Mock

ENGINE_ROOT = Path(__file__).resolve().parents[2]
ROLES = ("MNEMONIC", "MEMORY_EXTRACT", "MEMORY_MERGE")
ROLE_KEYS = tuple(f"MODEL_{role}" for role in ROLES)
PROVIDER_VAR = "MNEMONIC_CORPUS_PROVIDER"
ARMS_VAR = "MNEMONIC_CORPUS_ARMS"
ARM_VAR = "MNEMONIC_CORPUS_ARM"
DRY_SECRET = "corpus-dry-placeholder-key"
PROVIDERS = {
    "openrouter": {
        "transport": "openrouter",
        "secret": "OPENROUTER_API_KEY",
        "unpriced": "AI paused: OpenRouter model has no verified price ceiling.",
    },
    "anthropic": {
        "transport": "direct",
        "secret": "ANTHROPIC_API_KEY",
        "unpriced": "AI paused: model pricing is not configured for this model.",
    },
}
DECISION_EXAMPLE = "global_opening_hours"


class ArmRefused(RuntimeError):
    """The arm cannot be read from the measurement's arms; nothing booted."""


@dataclass(frozen=True)
class Arm:
    provider: str
    model: str
    source: str
    # The arm's catalogue id: the key of its results in measured.json.
    id: str

    @property
    def transport(self) -> str:
        return PROVIDERS[self.provider]["transport"]

    @property
    def secret_name(self) -> str:
        return PROVIDERS[self.provider]["secret"]

    @property
    def unpriced_message(self) -> str:
        return PROVIDERS[self.provider]["unpriced"]


def reference() -> str:
    path = ENGINE_ROOT / "zylch" / "llm" / "roles" / "requirements.json"
    return json.loads(path.read_text(encoding="utf-8"))["reference"]


def arm_from(environ: Mapping[str, str], *, live: bool) -> Arm:
    """The arm of this run, read from the measurement's arms (see the module docstring)."""
    provider = (environ.get(PROVIDER_VAR) or "openrouter").strip()
    if provider not in PROVIDERS:
        raise ArmRefused(f"{PROVIDER_VAR}={provider!r}: not one of {sorted(PROVIDERS)}")
    path, chosen = (environ.get(ARMS_VAR) or "").strip(), (environ.get(ARM_VAR) or "").strip()
    if not path:
        if live:
            raise ArmRefused(f"a live run reads its arm from {ARMS_VAR}; nothing booted")
        if provider != "openrouter":
            raise ArmRefused(f"a dry run on {provider} needs {ARMS_VAR} for a direct id")
        return Arm(provider, reference(), "reference (dry default)", reference())
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = {
        row["id"]: row
        for role in ROLES
        for row in ((document.get("roles") or {}).get(role) or {}).get("arms", [])
    }
    if chosen not in rows:
        raise ArmRefused(f"{ARM_VAR}={chosen!r} is not an arm of {', '.join(ROLES)} in {path}")
    model = chosen if provider == "openrouter" else rows[chosen].get("direct_id")
    if not model:
        raise ArmRefused(f"{chosen} has no direct id for the {provider} provider")
    return Arm(provider, model, f"{Path(path).name}:{chosen}", chosen)


def dry_arm() -> Arm:
    """The arm of a dry run that names none: the reference, on OpenRouter."""
    return arm_from({}, live=False)


# ─── Scripted wire ────────────────────────────────────────────────────


def text_response(arm: Arm, body: str, stop_reason: str = "end_turn"):
    """One text response with the receipt the arm's transport settles from."""
    usage = {"input_tokens": 400, "output_tokens": 120}
    if arm.transport == "openrouter":
        usage["cost"] = "0.000500"
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=body, refusal=None)],
        model=arm.model,
        stop_reason=stop_reason,
        usage=usage if arm.transport == "openrouter" else SimpleNamespace(**usage),
        refusal=None,
    )


def scripted_client(arm: Arm, *responses, model: str | None = None):
    """The real ``LLMClient`` of the arm's transport; only the wire is scripted.

    ``responses`` are texts, or response objects used as given.
    """
    from zylch.llm.client import LLMClient

    llm = LLMClient(transport=arm.transport, api_key=DRY_SECRET, model=model or arm.model)
    replies = [text_response(arm, r) if isinstance(r, str) else r for r in responses]
    llm._client.messages.create = Mock(side_effect=replies)
    return llm


# ─── Requests and their bounds ────────────────────────────────────────


@functools.cache
def _common():
    path = ENGINE_ROOT / "scripts" / "measurement_common.py"
    spec = importlib.util.spec_from_file_location("measurement_common_for_corpus", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def decision_request(case_id: str) -> dict:
    """The mnemonic decision request of one corpus case (``agent.decide``'s first round)."""
    from tests.memory import mnemonic_cases as cases
    from zylch.memory.mnemonic import prompts
    from zylch.memory.mnemonic.contracts import MNEMONIC_MAX_TOKENS

    event, candidates = cases.build(case_id)
    return {
        "system": prompts.system_blocks(),
        "messages": [{"role": "user", "content": prompts.user_message(event, candidates)}],
        "max_tokens": MNEMONIC_MAX_TOKENS,
    }


def extraction_request(spec: dict, prompt: str) -> dict:
    """The worker's extraction request for an automatic case's observation."""
    from zylch.workers import memory as mem_mod

    system = [{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}]
    user = "Analyze this email:\n\n" + spec["original_observation"]
    return {
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "max_tokens": mem_mod.EMAIL_EXTRACTION_MAX_TOKENS,
    }


def sent(arm: Arm, request: dict) -> dict:
    """The dict the engine's client would reserve and send for ``request`` on the arm."""
    from zylch.llm.client import LLMClient

    client = LLMClient(transport=arm.transport, api_key=DRY_SECRET, model=arm.model)
    return _common().reserved_request(client, **request)


def bound(arm: Arm, request: dict) -> int:
    """The engine's reservation for ``request`` on the arm's transport, in micro-USD."""
    from zylch.llm.budget_pricing import request_bound

    return request_bound(sent(arm, request), arm.transport)


def unpriced_client(arm: Arm, model: str):
    """A scripted client of the arm's transport for a model that transport cannot price."""
    return scripted_client(arm, text_response(arm, "{}"), model=model)
