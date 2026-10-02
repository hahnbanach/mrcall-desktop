"""The published contract (schema 1): its schemas, examples, build snapshot and static gates.

`zylch/llm/roles/contract/` holds the JSON Schemas of `table.json` and
`snapshot.json` with one example each; `zylch/llm/roles/gates.py` applies the
schemas (its own interpreter of the keywords they use) and the rules beyond
them. These cases check that the schemas accept the examples and the build
snapshot, that the examples pass every gate, and that each gate rejects a
document crafted to break it and only it — so every rule the billing server
reimplements from `contract/README.md` is shown to bite here. Where the
`jsonschema` package is installed, the schemas are also checked as JSON
Schema draft 2020-12 against the same documents.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from zylch.llm.roles import gates

ROLES = Path(__file__).resolve().parents[2] / "zylch" / "llm" / "roles"
CONTRACT = ROLES / "contract"
OPUS, SONNET = "anthropic/claude-opus-5.5", "anthropic/claude-sonnet-5.5"
QWEN, K3 = "qwen/qwen3.8-max-0902", "moonshotai/kimi-k3"
# The requirements the examples are written against (contract/README.md).
REQUIREMENTS = {
    "presets": {"economy": {"ceiling": 10}, "balanced": {"ceiling": 20}},
    "roles": {"CHAT": {}, "MNEMONIC": {}},
    "excluded_families": [{"vendor": "anthropic", "token": "haiku"}],
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def snapshot() -> dict:
    return load(CONTRACT / "snapshot.example.json")


@pytest.fixture
def table() -> dict:
    return load(CONTRACT / "table.example.json")


def violations(call, *args) -> list[str]:
    with pytest.raises(gates.GateError) as failed:
        call(*args)
    return failed.value.violations


# ------------------------------------------------- the schemas and examples


def test_the_schemas_accept_the_examples_and_the_build_snapshot():
    assert gates.schema_errors(load(CONTRACT / "table.example.json"), "table") == []
    assert gates.schema_errors(load(CONTRACT / "snapshot.example.json"), "snapshot") == []
    build = load(ROLES / "snapshot.json")
    assert gates.schema_errors(build, "snapshot") == []
    gates.check_snapshot(build)
    assert len(build["models"]) > 400 and build["direct"]


def test_the_examples_pass_every_gate(table, snapshot):
    gates.check_snapshot(snapshot)
    gates.check_table(table, REQUIREMENTS, snapshot)
    # An empty Anthropic ranking is allowed; the example holds one.
    assert table["presets"]["economy"]["roles"]["MNEMONIC"]["anthropic_ranking"] == []


def test_the_schemas_are_json_schema_2020_12_and_agree_with_the_interpreter(table, snapshot):
    jsonschema = pytest.importorskip("jsonschema")
    for name, doc in (("table", table), ("snapshot", snapshot)):
        validator = jsonschema.Draft202012Validator(gates.schema(name))
        jsonschema.Draft202012Validator.check_schema(gates.schema(name))
        assert not list(validator.iter_errors(doc))
        for broken in schema_breaks(name, doc):
            assert list(validator.iter_errors(broken)), broken
            assert gates.schema_errors(broken, name), broken
    snapshot_validator = jsonschema.Draft202012Validator(gates.schema("snapshot"))
    assert not list(snapshot_validator.iter_errors(load(ROLES / "snapshot.json")))


def schema_breaks(name: str, doc: dict) -> list[dict]:
    """Documents that break one schema rule each."""
    out = []

    def broken(change) -> None:
        copied = copy.deepcopy(doc)
        change(copied)
        out.append(copied)

    broken(lambda d: d.update(schema=2))
    broken(lambda d: d.update(version="ABC"))
    broken(lambda d: d.update(extra=True))
    broken(lambda d: d.pop("presets" if name == "table" else "models"))
    if name == "table":
        role = ("presets", "balanced", "roles", "CHAT")
        broken(lambda d: _at(d, role)["ranking"].extend([{"id": "v/x", "direct_id": None}] * 2))
        broken(lambda d: _at(d, role)["ranking"][0].update(direct_id=7))
        broken(lambda d: _at(d, ("presets", "economy")).update(ceiling="10.0"))
        broken(lambda d: _at(d, ("presets", "economy")).update(ceiling=10))
        broken(lambda d: _at(d, ("presets",)).update(Economy=d["presets"]["economy"]))
        broken(lambda d: _at(d, ("presets", "economy", "roles")).update(chat={}))
        broken(lambda d: d.update(resolved_at="2026-10-02 14:05"))
    else:
        broken(lambda d: _at(d, ("models", QWEN, "pricing")).update(output="6.0"))
        broken(lambda d: _at(d, ("models", QWEN, "pricing")).update(input="-2"))
        broken(lambda d: _at(d, ("models", QWEN, "pricing")).update(input=2))
        broken(lambda d: _at(d, ("models", QWEN, "metadata")).pop("forced_tool"))
        broken(lambda d: _at(d, ("models", QWEN, "metadata", "reasoning")).update(mandatory=1))
        broken(lambda d: _at(d, ("models", QWEN, "metadata")).update(parameters=["a", "a"]))
        broken(lambda d: _at(d, ("models", QWEN, "metadata")).update(context_length=1.5))
        broken(lambda d: _at(d, ("models", QWEN, "endpoints"))[0]["pricing"].update(input=None))
        broken(lambda d: _at(d, ("models", QWEN)).update(endpoints={}))
        broken(lambda d: _at(d, ("models",)).update({"has space": d["models"][QWEN]}))
        broken(lambda d: _at(d, ("policy",)).update(margin=1.25))
    return out


def _at(doc: dict, path: tuple) -> dict:
    for key in path:
        doc = doc[key]
    return doc


@pytest.mark.parametrize("name", ["table", "snapshot"])
def test_the_interpreter_rejects_each_schema_break(name, table, snapshot):
    doc = table if name == "table" else snapshot
    for broken in schema_breaks(name, doc):
        found = violations(
            gates.check_table if name == "table" else gates.check_snapshot,
            *((broken, REQUIREMENTS, snapshot) if name == "table" else (broken,)),
        )
        assert found and all(v.startswith("schema: ") for v in found), found


def test_the_interpreter_refuses_what_it_does_not_interpret():
    with pytest.raises(ValueError, match="not interpreted"):
        gates._conform({}, {"type": "object", "minProperties": 1}, {}, "$", [])
    with pytest.raises(ValueError, match="not anchored"):
        gates._conform("x", {"type": "string", "pattern": "x"}, {}, "$", [])
    with pytest.raises(ValueError, match="not interpreted"):
        gates._conform("x", {"$ref": "other.json#/x"}, {}, "$", [])


# ------------------------------------------------------- version and layout


def test_version_is_the_sha256_of_the_canonical_json():
    doc = {"b": "è", "a": [1, {"d": None, "c": True}], "version": "ignored"}
    assert gates.canonical(doc) == '{"a":[1,{"c":true,"d":null}],"b":"è"}'.encode("utf-8")
    reordered = {"version": "other", "a": [1, {"c": True, "d": None}], "b": "è"}
    assert gates.version_of(doc) == gates.version_of(reordered)
    assert gates.stamped(doc)["version"] == gates.version_of(doc) != gates.version_of({})


def test_the_layout_round_trips_and_puts_a_model_on_a_line(snapshot):
    text = gates.dump(snapshot, 2)
    assert json.loads(text) == snapshot
    lines = text.splitlines()
    assert sum(line.startswith('  "') for line in lines) == len(snapshot["models"]) + len(
        snapshot["direct"]
    ) + len(snapshot["policy"])


# ------------------------------------------------------- the snapshot gates


def test_a_snapshot_whose_version_does_not_match_is_refused(snapshot):
    snapshot["models"][QWEN]["pricing"]["output"] = "7"
    assert violations(gates.check_snapshot, snapshot) == [
        f"version: {snapshot['version']} is not the content's"
    ]


def test_a_direct_entry_must_name_its_catalogue_entry_under_its_direct_id(snapshot):
    moved = copy.deepcopy(snapshot)
    moved["direct"]["claude-sonnet-5"] = moved["direct"].pop("claude-sonnet-5-5")
    assert violations(gates.check_snapshot, gates.stamped(moved)) == [
        f"direct: claude-sonnet-5 is not the direct id of {SONNET}"
    ]
    orphan = copy.deepcopy(snapshot)
    del orphan["models"][SONNET]
    assert violations(gates.check_snapshot, gates.stamped(orphan)) == [
        f"direct: claude-sonnet-5-5 names {SONNET}, which the snapshot lacks"
    ]


# ---------------------------------------------------------- the table gates


def broken_table(table: dict, change) -> dict:
    """`table` changed by `change` and stamped again, so only the change fails."""
    copied = copy.deepcopy(table)
    change(copied)
    return gates.stamped(copied)


def chat(table: dict, preset: str = "balanced") -> dict:
    return table["presets"][preset]["roles"]["CHAT"]


def rejects(table, snapshot, change, *expected) -> None:
    found = violations(gates.check_table, broken_table(table, change), REQUIREMENTS, snapshot)
    assert found == list(expected)


def test_a_table_whose_version_does_not_match_is_refused(table, snapshot):
    chat(table)["ranking"].reverse()
    found = violations(gates.check_table, table, REQUIREMENTS, snapshot)
    assert found == [f"version: {table['version']} is not the content's"]


def test_coverage_every_preset_and_role_in_force_has_a_ranking(table, snapshot):
    rejects(
        table,
        snapshot,
        lambda t: chat(t, "economy").update(ranking=[]),
        "coverage: economy / CHAT has no ranking",
    )
    rejects(
        table,
        snapshot,
        lambda t: t["presets"]["economy"]["roles"].pop("MNEMONIC"),
        "coverage: economy / MNEMONIC has no ranking",
    )
    rejects(
        table,
        snapshot,
        lambda t: t["presets"].pop("balanced"),
        "coverage: preset balanced is missing",
    )
    # A role beyond the requirements is checked but not required.
    extra = broken_table(
        table, lambda t: t["presets"]["economy"]["roles"].update(NEW=chat(t, "economy"))
    )
    gates.check_table(extra, REQUIREMENTS, snapshot)


def test_a_raised_ceiling_is_refused(table, snapshot):
    rejects(
        table,
        snapshot,
        lambda t: t["presets"]["economy"].update(ceiling="12"),
        "ceiling: economy is 12, above the 10 in force",
    )
    lowered = broken_table(table, lambda t: t["presets"]["balanced"].update(ceiling="25"))
    relaxed = copy.deepcopy(REQUIREMENTS)
    relaxed["presets"]["balanced"]["ceiling"] = 30
    gates.check_table(lowered, relaxed, snapshot)


def test_aliases_excluded_families_and_expiries_are_never_ranked(table, snapshot):
    alias = "~anthropic/claude-haiku-latest"
    rejects(
        table,
        snapshot,
        lambda t: chat(t)["ranking"].append({"id": alias, "direct_id": None}),
        f"balanced / CHAT / ranking: {alias} is an alias",
        f"balanced / CHAT / ranking: {alias} is of the excluded family anthropic + haiku",
    )
    haiku = copy.deepcopy(snapshot)
    haiku["models"]["anthropic/claude-haiku-4.5"] = haiku["models"][SONNET]
    haiku = gates.stamped(haiku)
    found = violations(
        gates.check_table,
        broken_table(
            table,
            lambda t: chat(t)["ranking"].append(
                {"id": "anthropic/claude-haiku-4.5", "direct_id": None}
            ),
        ),
        REQUIREMENTS,
        haiku,
    )
    assert found == [
        "balanced / CHAT / ranking: anthropic/claude-haiku-4.5 is of the excluded family"
        " anthropic + haiku"
    ]
    expiring = copy.deepcopy(snapshot)
    expiring["models"][QWEN]["metadata"]["expiration_date"] = "2026-10-09"
    expiring = gates.stamped(expiring)
    found = violations(gates.check_table, table, REQUIREMENTS, expiring)
    assert found == [
        f"{preset} / {role} / ranking: {QWEN} expires on 2026-10-09"
        for preset, role in (("balanced", "CHAT"), ("economy", "CHAT"), ("economy", "MNEMONIC"))
    ]


def test_ranked_ids_are_priced_positive_and_within_the_ceiling(table, snapshot):
    rejects(
        table,
        snapshot,
        lambda t: chat(t)["ranking"].append({"id": "vendor/unknown-1", "direct_id": None}),
        "balanced / CHAT / ranking: vendor/unknown-1 is not in the snapshot",
    )
    rejects(
        table,
        snapshot,
        lambda t: chat(t, "economy")["ranking"].append({"id": K3, "direct_id": None}),
        f"economy / CHAT / ranking: {K3} costs 13.5 per million output tokens,"
        " above the ceiling of 10",
    )
    for side in ("input", "output"):
        for price in ("0", None):
            free = copy.deepcopy(snapshot)
            free["models"][K3]["pricing"][side] = price
            found = violations(gates.check_table, table, REQUIREMENTS, gates.stamped(free))
            assert found == [
                f"balanced / {role} / ranking: {K3} has no positive input and output price"
                for role in ("CHAT", "MNEMONIC")
            ]


def test_direct_ids_follow_the_rule_and_are_priced(table, snapshot):
    rejects(
        table,
        snapshot,
        lambda t: chat(t)["ranking"][0].update(direct_id="claude-opus-5"),
        f"balanced / CHAT / ranking: {OPUS} carries the direct id claude-opus-5,"
        " not claude-opus-5-5",
    )
    rejects(
        table,
        snapshot,
        lambda t: chat(t)["ranking"][2].update(direct_id="qwen3.8-max-0902"),
        f"balanced / CHAT / ranking: {QWEN} carries the direct id qwen3.8-max-0902, not None",
    )
    unpriced = copy.deepcopy(snapshot)
    del unpriced["direct"]["claude-opus-5-5"]
    found = violations(gates.check_table, table, REQUIREMENTS, gates.stamped(unpriced))
    assert f"balanced / CHAT / ranking: {OPUS} has the direct id claude-opus-5-5, which the" in (
        found[0]
    )
    dear = copy.deepcopy(snapshot)
    dear["direct"]["claude-sonnet-5-5"]["pricing"]["output"] = "11"
    found = violations(gates.check_table, table, REQUIREMENTS, gates.stamped(dear))
    assert found == [
        f"economy / CHAT / {column}: {SONNET} (direct claude-sonnet-5-5) costs 11 per million"
        " output tokens, above the ceiling of 10"
        for column in ("ranking", "anthropic_ranking")
    ]


def test_the_anthropic_ranking_holds_only_anthropic_models_with_a_direct_id(table, snapshot):
    rejects(
        table,
        snapshot,
        lambda t: chat(t)["anthropic_ranking"].append({"id": QWEN, "direct_id": None}),
        f"balanced / CHAT / anthropic_ranking: {QWEN} has no direct id in the Anthropic ranking",
        f"balanced / CHAT / anthropic_ranking: {QWEN} is not an Anthropic model,"
        " in the Anthropic ranking",
    )
    rejects(
        table,
        snapshot,
        lambda t: chat(t)["anthropic_ranking"][1].update(direct_id=None),
        f"balanced / CHAT / anthropic_ranking: {SONNET} has no direct id in the Anthropic ranking",
    )


def test_an_id_is_ranked_once(table, snapshot):
    rejects(
        table,
        snapshot,
        lambda t: chat(t)["ranking"].append(chat(t)["ranking"][0]),
        "balanced / CHAT / ranking: an id is ranked twice",
    )


def test_every_violation_is_named_at_once(table, snapshot):
    def two(t):
        t["presets"]["economy"].update(ceiling="11")
        chat(t)["ranking"].append({"id": "~v/alias", "direct_id": None})

    broken = broken_table(table, two)
    found = violations(gates.check_table, broken, REQUIREMENTS, snapshot)
    assert found == [
        "ceiling: economy is 11, above the 10 in force",
        "balanced / CHAT / ranking: ~v/alias is an alias",
        "balanced / CHAT / ranking: ~v/alias is not in the snapshot",
    ]
    with pytest.raises(gates.GateError) as failed:
        gates.check_table(broken, REQUIREMENTS, snapshot)
    assert all(v in str(failed.value) for v in found)
