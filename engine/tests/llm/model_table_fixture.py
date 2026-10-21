"""The fixture model table every test resolves from (milestone 10, slice S6).

`fixtures/llm/model-table/` holds a decision record (`table.json`) and a
snapshot (`snapshot.json`) of the published contract (schema 1,
`zylch/llm/roles/contract/`), so that no test depends on the build copies,
which the coordinator refreshes from live reads, or on a download. They are
built here, never edited by hand (`test_model_table.py` checks the committed
files are what `build()` gives):

- the snapshot is the 2026-10-02 capture's (`resolver_fixture.sources()`, the
  contract example's source) cut to the models the table ranks, plus the
  Haiku family (a catalogue entry, its alias and its direct id: a model a
  profile may save, never one a ranking or Settings offers) and Opus 5 (a
  model a profile may save that no ranking holds);
- the table ranks, for every role of the committed `requirements.json` and
  both presets, a short list by the role's rule (a `maximise` role by its
  index, a `satisfice` role cheapest first), its Anthropic ranking being the
  same list's Anthropic entries. The lists are chosen so each run-time case
  has a role to show it: under `economy` no role ranks K3 (above the
  ceiling) and every role ranks an Anthropic model, so the profile every test
  starts with (a personal Anthropic key, `custom` with nothing saved, read as
  `economy`) never pauses; under `balanced` every role ranks K3 and
  `MNEMONIC` ranks no Anthropic model (a personal Anthropic key pauses on
  it); the `satisfice` roles and the `maximise` ones under `economy` rank
  Sonnet 5, which a billing server may list by its catalogue id.

`install()` puts the table in force (`table.set_table`), as the root
conftest does for every test; `doc()` returns a fresh copy of a committed file.
"""

from __future__ import annotations

import copy
import hashlib
import json
from functools import cache, lru_cache
from pathlib import Path

from zylch.llm.roles import candidates, gates, snapshot

from .resolver_fixture import READ_AT, requirements, sources

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "llm" / "model-table"
OPUS, SONNET = "anthropic/claude-opus-5.5", "anthropic/claude-sonnet-5.5"
SONNET5, OPUS5 = "anthropic/claude-sonnet-5", "anthropic/claude-opus-5"
K3, QWEN, FLASH = "moonshotai/kimi-k3", "qwen/qwen3.8-max-0902", "z-ai/glm-5.3-flash"
HAIKU, HAIKU_ALIAS = "anthropic/claude-haiku-4.5", "~anthropic/claude-haiku-latest"
# Per preset: the ranking of a `maximise` role and of a `satisfice` role;
# MNEMONIC's under `balanced` (no Anthropic model: an empty Anthropic ranking).
RANKINGS = {
    "economy": {"maximise": [SONNET, QWEN, SONNET5], "satisfice": [FLASH, QWEN, SONNET5]},
    "balanced": {"maximise": [OPUS, SONNET, QWEN, K3], "satisfice": [FLASH, QWEN, SONNET5, K3]},
}
MNEMONIC = {"balanced": [K3, QWEN]}
SAVED_ONLY = (HAIKU, HAIKU_ALIAS, OPUS5)
SYNTHETIC = hashlib.sha256(b"fixture model table").hexdigest()


@lru_cache(maxsize=1)
def _capture() -> dict:
    src = sources()
    rules = candidates.policy(requirements())
    return snapshot.build(src["catalogue"], src["endpoints"], rules, src["read_at"])


def build_snapshot() -> dict:
    """The capture's snapshot cut to the ranked and saved-only models."""
    full = _capture()
    ranked = {model for lists in RANKINGS.values() for row in lists.values() for model in row}
    keep = sorted(ranked | set(SAVED_ONLY))
    models = {model: copy.deepcopy(full["models"][model]) for model in keep}
    direct = {
        key: copy.deepcopy(row)
        for key, row in full["direct"].items()
        if row["catalogue_id"] in keep
    }
    body = {
        "schema": gates.SCHEMA,
        "read_at": full["read_at"],
        "policy": copy.deepcopy(full["policy"]),
        "models": models,
        "direct": direct,
    }
    return gates.stamped(body)


def _entries(models: list[str], snap: dict) -> list[dict]:
    out = []
    for model in models:
        direct = gates.direct_id(model)
        out.append({"id": model, "direct_id": direct if direct in snap["direct"] else None})
    return out


def build_table(snap: dict) -> dict:
    """Both presets, every role of the committed requirements, as the docstring says."""
    req = requirements()
    presets = {}
    for preset, lists in RANKINGS.items():
        body = {}
        for role, rule in req["roles"].items():
            special = MNEMONIC.get(preset) if role == "MNEMONIC" else None
            models = special or lists[rule["rule"]]
            ranking = _entries(models, snap)
            body[role] = {
                "ranking": ranking,
                "anthropic_ranking": [e for e in ranking if e["direct_id"] is not None],
            }
        presets[preset] = {"ceiling": str(req["presets"][preset]["ceiling"]), "roles": body}
    record = {
        "schema": gates.SCHEMA,
        "resolved_at": "2026-10-02T14:05:00Z",
        "catalogue_read_at": READ_AT,
        "requirements_sha256": SYNTHETIC,
        "measured_sha256": SYNTHETIC,
        "presets": presets,
    }
    return gates.stamped(record)


def build() -> dict[str, dict]:
    snap = build_snapshot()
    return {"snapshot.json": snap, "table.json": build_table(snap)}


def text(name: str, document: dict) -> str:
    """The committed layout (`gates.dump`): a line per model, a line per role."""
    return gates.dump(document, 2 if name == "snapshot.json" else 4) + "\n"


@cache
def _committed(name: str) -> str:
    return (FIXTURE / name).read_text(encoding="utf-8")


def doc(name: str) -> dict:
    """A fresh copy of a committed fixture document."""
    return json.loads(_committed(name))


def install() -> dict:
    """Put the fixture table in force; returns it."""
    from zylch.llm.roles import table

    record = doc("table.json")
    table.set_table(record)
    return record


def served_entry(model: str, provider: str, record: dict | None = None) -> dict:
    """One model of a v2 ``/capabilities`` answer, as the billing server writes it
    (`protocol-v2.md`): v1's ``{id, label, provider}`` plus `price`, `as_of`,
    `table_version` and the `roles` whose ranking lists it (by catalogue id)."""
    record = record or doc("table.json")
    catalogue_id = model if "/" in model else f"anthropic/{model}"
    places = [
        {"preset": preset, "role": role, "rank": rank}
        for preset, body in sorted(record["presets"].items())
        for role, rankings in sorted(body["roles"].items())
        for rank, entry in enumerate(rankings["ranking"], 1)
        if model in (entry["id"], entry["direct_id"])
    ]
    return {
        "id": model,
        "label": catalogue_id.split("/", 1)[1],
        "provider": provider,
        "price": "15",
        "as_of": READ_AT,
        "table_version": record["version"],
        "roles": places,
    }


def everything() -> list[dict]:
    """A server serving every model the fixture table ranks: each direct id as
    Anthropic's, each catalogue id as OpenRouter's (direct ids first)."""
    record = doc("table.json")
    ranked = [
        entry
        for body in record["presets"].values()
        for rankings in body["roles"].values()
        for entry in rankings["ranking"]
    ]
    direct = dict.fromkeys(e["direct_id"] for e in ranked if e["direct_id"])
    catalogue = dict.fromkeys(e["id"] for e in ranked)
    return [served_entry(m, "anthropic", record) for m in direct] + [
        served_entry(m, "openrouter", record) for m in catalogue
    ]


def capabilities(models: list[dict], protocol: str = "mrcall-bounded-v2") -> dict:
    """A ``/capabilities`` answer listing `models`."""
    return {
        "protocol": protocol,
        "currency": "USD",
        "streaming": False,
        "features": ["text", "function_tools"],
        "max_tokens": 8192,
        "models": models,
    }


def serve(models: list[dict], url: str | None = None) -> None:
    """Fill the served set of `url` (the default billing server) as a fresh read
    of a v2 server listing `models`: credits resolve from it with no network."""
    from zylch.llm.model_policy import PROXY_URL
    from zylch.llm.roles import served

    served._cache[url or PROXY_URL] = (served._clock(), served.parse(capabilities(models)))


if __name__ == "__main__":  # regenerate: python -m tests.llm.model_table_fixture
    FIXTURE.mkdir(parents=True, exist_ok=True)
    for name, document in build().items():
        (FIXTURE / name).write_text(text(name, document), encoding="utf-8")
