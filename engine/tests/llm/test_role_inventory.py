"""The role inventory (milestone 10a, brief D6): every LLM client the engine builds is counted.

Milestone 10 gives every paid call site a role whose model the resolver
chooses. That only holds while the set of sites is known, so this file freezes
it, as ``tests/memory/test_mnemonic_inventory.py`` freezes the memory writers:

- every call of ``make_llm_client`` / ``try_make_llm_client`` under ``zylch/``
  is classified by ``model_inventory_scan.client_sites`` — ``caller`` (no
  model: the factory's base model decides, the sites the roster must name),
  ``caller_with_model`` (a model passed) or ``probe`` (built only to test
  ``is None``, client discarded — the sites ``llm_available()`` replaces) —
  and the per-file count of each kind must equal
  ``tests/fixtures/llm/role_inventory.json``. A new bare ``make_llm_client()``
  fails with its file named; a removed or converted one fails until the
  inventory is updated, in review;
- every ``routed_model("MODEL_…")`` is counted per file and env key the same
  way, so a role routed from a new place, or a role key renamed, is a
  reviewed change;
- every model-less caller carries the role the plan's roster assigns it, and
  the probes number fourteen, as the plan counts them.

Line numbers in the inventory are informational; counts are what is frozen,
so an edit elsewhere in a file does not break the test.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from .model_inventory_scan import client_sites, counted, routed_sites

ENGINE_ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ENGINE_ROOT / "tests" / "fixtures" / "llm" / "role_inventory.json"
KINDS = ("caller", "caller_with_model", "probe")
# The roster is the one requirements.json declares (slice 2), so a role named
# here and a role the resolver resolves cannot drift apart; PROBE and the
# factory's own delegation are the two non-roles an inventory row may carry.
REQUIREMENTS = ENGINE_ROOT / "zylch" / "llm" / "roles" / "requirements.json"
ROLES = frozenset(json.loads(REQUIREMENTS.read_text())["roles"]) | {"PROBE", "FACTORY"}
PLAN_PROBES = 14


def _inventory() -> dict:
    return json.loads(INVENTORY.read_text())


def _sources(inventory: dict) -> list[tuple[str, Path]]:
    root = ENGINE_ROOT / inventory["scope"]
    return [(p.relative_to(ENGINE_ROOT).as_posix(), p) for p in sorted(root.rglob("*.py"))]


def _scanned_constructors(inventory: dict) -> list[dict]:
    return [
        {"file": rel, **site} for rel, path in _sources(inventory) for site in client_sites(path)
    ]


def _diff(found: Counter, frozen: Counter) -> str:
    lines = [
        f"{key}: found {found[key]}, inventory {frozen[key]}"
        for key in sorted(set(found) | set(frozen))
        if found[key] != frozen[key]
    ]
    return "\n  ".join(lines)


@pytest.mark.parametrize("kind", KINDS)
def test_client_constructions_per_file_match_the_inventory(kind):
    inventory = _inventory()
    found = counted([s for s in _scanned_constructors(inventory) if s["kind"] == kind], "file")
    frozen = counted([s for s in inventory["constructors"] if s["kind"] == kind], "file")
    assert found == frozen, (
        f"{kind} sites differ from tests/fixtures/llm/role_inventory.json "
        "(a client built without a model must name a role; update the inventory in review):\n  "
        + _diff(found, frozen)
    )


def test_routed_model_sites_per_file_and_key_match_the_inventory():
    inventory = _inventory()
    found = Counter(
        (rel, key) for rel, path in _sources(inventory) for _, key in routed_sites(path)
    )
    frozen = counted(inventory["routed_model"], "file", "env_key")
    assert found == frozen, "routed_model sites differ:\n  " + _diff(found, frozen)


def test_every_site_names_a_roster_role():
    for row in _inventory()["constructors"]:
        assert row["kind"] in KINDS, row
        assert row["role"] in ROLES, f"role not in the plan's roster: {row}"
        assert (row["role"] == "PROBE") == (row["kind"] == "probe"), row


def test_the_probes_are_the_plans_fourteen():
    probes = [s for s in _inventory()["constructors"] if s["kind"] == "probe"]
    assert len(probes) == PLAN_PROBES
    assert all(s["call"] == "try_make_llm_client" for s in probes)


SYNTHETIC = {
    "bare caller": ("c = make_llm_client()\n", "caller"),
    "kept by try": ("c = try_make_llm_client()\nif c is None:\n    pass\n", "caller"),
    "probe is None": ("if try_make_llm_client() is None:\n    pass\n", "probe"),
    "probe is not None": ("ok = try_make_llm_client() is not None\n", "probe"),
    "probe not": ("if not try_make_llm_client():\n    pass\n", "probe"),
    "probe bare test": ("if try_make_llm_client():\n    pass\n", "probe"),
    "model keyword": ('c = make_llm_client(model=routed_model("MODEL_X"))\n', "caller_with_model"),
    "model positional": ("c = llm.make_llm_client(name)\n", "caller_with_model"),
}


@pytest.mark.parametrize("name", sorted(SYNTHETIC))
def test_each_spelling_is_classified(tmp_path, name):
    source, kind = SYNTHETIC[name]
    path = tmp_path / "site.py"
    path.write_text("# make_llm_client() in a comment is not a call\n" + source)
    assert [s["kind"] for s in client_sites(path)] == [kind]
