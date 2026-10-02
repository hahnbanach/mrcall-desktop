"""The fixture snapshot the price tests read (milestone 10, slice S3).

`fixtures/llm/snapshot-2026-10-02.json` is the snapshot the engine's own
builder (`roles/snapshot.build`) makes from the committed 2026-10-02 capture
(`fixtures/llm/resolver-2026-10-02/`, read by the resolver's script at
13:36Z), cut to the entries the price tests name (`select`): every direct id
with its catalogue entry; milestone 10a's OpenRouter picks and billed models;
a model whose cheapest endpoint is a `flex` service tier the policy excludes
(`openai/gpt-6.1-sol`); one whose endpoints were not read (fewer than
200,000 tokens of context); one whose endpoints were read and none admitted;
one with a variable price; and a `:free` variant the catalogue prices at
0 (`qwen/qwen3.8-27b:free`). It is committed with the tests so a price a
test pins never moves when the coordinator refreshes the build copy
(`roles/snapshot.json`) from a live read; `test_snapshot_prices.py` holds it
equal to a fresh cut of the capture and through the static gates.
Regenerate it after a builder change with `gates.dump(select(built()), 2)`.

The variants a test needs are derived from it, never written by hand:
`priced_at` moves a price, `successor` adds a newer Sonnet, `degraded` drops
an admitted endpoint (as a day the provider was down when the catalogue was
read), and `as_billed_by_10a` puts back the two OpenRouter rates milestone
10a billed that were not the catalogue's (`BILLED_10A`), so a test written
before the snapshot keeps its prices and its OpenRouter ceilings move by
exactly the margin (brief AC 4). Each is stamped with its own `version`.
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path

from zylch.llm.roles import candidates, gates, snapshot

from .resolver_fixture import requirements, sources

FILE = Path(__file__).resolve().parents[1] / "fixtures" / "llm" / "snapshot-2026-10-02.json"
K3 = "moonshotai/kimi-k3"
GLM_5_2 = "z-ai/glm-5.2"
SONNET_5 = "anthropic/claude-sonnet-5"
SONNET = "anthropic/claude-sonnet-5.5"
FLEX = "openai/gpt-6.1-sol"
UNREAD = "cohere/command-a-plus"
NONE_ADMITTED = "moonshotai/kimi-k2.6"
VARIABLE = "openrouter/auto"
FREE = "qwen/qwen3.8-27b:free"
MODELS = (
    K3,
    GLM_5_2,
    "z-ai/glm-5.3-flash",
    "xiaomi/mimo-v2.6-flash",
    "qwen/qwen3.8-max-0902",
    FLEX,
    UNREAD,
    NONE_ADMITTED,
    VARIABLE,
    FREE,
)
# The newer Sonnet a simulated successor adds, and its direct id.
SUCCESSOR, SUCCESSOR_DIRECT = "anthropic/claude-sonnet-6", "claude-sonnet-6"
# K3's pinned endpoint (k3_reasoning.ENDPOINT).
K3_ENDPOINT = "digitalocean"
# The OpenRouter rates 10a billed (requirements.json's allowlist) where they
# were not the catalogue's: GLM 5.2's, and K3's provider-pinned rate, which
# `as_billed_by_10a` writes as K3's model-level price and its pinned endpoint's.
BILLED_10A = {GLM_5_2: ("0.6", "2"), K3: ("2.648138063", "13.28272425")}


def built() -> dict:
    """The whole snapshot of the 2026-10-02 capture, as the builder makes it."""
    src = sources()
    rules = candidates.policy(requirements())
    return snapshot.build(src["catalogue"], src["endpoints"], rules, src["read_at"])


def select(full: dict) -> dict:
    """`full` cut to the fixture's entries: every direct id and its catalogue
    entry, plus `MODELS`; stamped with the cut's own `version`."""
    wanted = [row["catalogue_id"] for row in full["direct"].values()] + list(MODELS)
    doc = {key: full[key] for key in ("schema", "read_at", "policy")}
    doc["models"] = {model: full["models"][model] for model in sorted(set(wanted))}
    doc["direct"] = dict(full["direct"])
    return gates.stamped(doc)


@lru_cache(maxsize=1)
def _committed() -> dict:
    return json.loads(FILE.read_text(encoding="utf-8"))


def fixture() -> dict:
    """The committed fixture snapshot, as a fresh copy a test may change."""
    return copy.deepcopy(_committed())


def priced_at(doc: dict, model: str, **prices: str) -> dict:
    """`doc` with `model`'s model-level `prices` (input, output, ...) replaced."""
    doc = copy.deepcopy(doc)
    doc["models"][model]["pricing"].update(prices)
    return gates.stamped(doc)


def successor(doc: dict) -> dict:
    """`doc` with a newer Sonnet beside the current one: the current entry's
    metadata and endpoints, a dearer price, a direct id of its own."""
    doc = copy.deepcopy(doc)
    newer = copy.deepcopy(doc["models"][SONNET])
    newer["pricing"].update(input="3", output="15")
    for endpoint in newer["endpoints"]:
        endpoint["pricing"].update(input="3", output="15")
    doc["models"][SUCCESSOR] = newer
    doc["direct"][SUCCESSOR_DIRECT] = {
        "catalogue_id": SUCCESSOR,
        "pricing": copy.deepcopy(newer["pricing"]),
        "metadata": copy.deepcopy(doc["direct"]["claude-sonnet-5-5"]["metadata"]),
    }
    return gates.stamped(doc)


def degraded(doc: dict, model: str, tag: str) -> dict:
    """`doc` with the admitted endpoint `tag` of `model` gone (down when read)."""
    doc = copy.deepcopy(doc)
    row = doc["models"][model]
    row["endpoints"] = [e for e in row["endpoints"] if e["tag"] != tag]
    return gates.stamped(doc)


def as_billed_by_10a(doc: dict) -> dict:
    """`doc` with `BILLED_10A`'s rates in place of the capture's: the snapshot
    10a's billing amounts to (every other rate 10a billed is the capture's)."""
    doc = copy.deepcopy(doc)
    for model, (i, o) in BILLED_10A.items():
        doc["models"][model]["pricing"].update(input=i, output=o)
    i, o = BILLED_10A[K3]
    for endpoint in doc["models"][K3]["endpoints"]:
        if endpoint["tag"] == K3_ENDPOINT:
            endpoint["pricing"].update(input=i, output=o)
    return gates.stamped(doc)
