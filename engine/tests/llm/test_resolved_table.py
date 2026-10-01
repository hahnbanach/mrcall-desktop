"""The committed resolved table against the committed fixture and requirements.

`zylch/llm/roles/resolved.json` is what `scripts/resolve_models.py --apply`
wrote from the reference fixture (`fixtures/llm/resolver/`, the OpenRouter
catalogue and benchmarks of 2026-10-01) and `zylch/llm/roles/requirements.json`.
Until the CI drift job has its secret, this file is the guard against a table
that no longer follows from its inputs: a changed ceiling, floor or role
without `--apply`, or a hand edit of the table, fails here. It also checks
that every model the table names (main pick, Anthropic fallback, MrCall
column; every preset and role) can take the engine's tool calls and its
admitted context, as the fixture's catalogue states them.
"""

import json
from pathlib import Path

import pytest
from zylch.llm.roles import resolver

ENGINE = Path(__file__).resolve().parents[2]
ROLES = ENGINE / "zylch" / "llm" / "roles"
FIXTURES = ENGINE / "tests" / "fixtures" / "llm"
REQUIRED_PARAMETERS = {"tools", "tool_choice"}


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_fixture(requirements: Path, fixture: Path) -> dict:
    """The table the resolver gives for a requirements file and a fixture."""
    read_at = fixture / "read-at.txt"
    raw = {
        "catalogue": (fixture / "models.json").read_bytes(),
        "benchmarks": (fixture / "benchmarks.json").read_bytes(),
        "read_at": read_at.read_text(encoding="utf-8").strip() if read_at.is_file() else None,
    }
    req = resolver.validate_requirements(load(requirements))
    return resolver.document(req, resolver.resolve(req, raw))


def named_models(table: dict) -> list[tuple[str, str, str, str]]:
    """Every (preset, role, column, catalogue id) the table names."""
    out = []
    for preset, outcome in table["presets"].items():
        for role, row in outcome["roles"].items():
            columns = {"pick": row, "anthropic_fallback": row["anthropic_fallback"]}
            columns["mrcall"] = row["mrcall"]
            for column, pick in columns.items():
                if pick is not None:
                    out.append((preset, role, column, pick["catalogue_id"]))
    return out


def test_the_committed_table_is_what_the_committed_inputs_give():
    committed = load(ROLES / "resolved.json")
    fresh = resolve_fixture(ROLES / "requirements.json", FIXTURES / "resolver")
    committed.pop("as_of")
    fresh.pop("as_of")
    assert fresh == committed, (
        "resolved.json no longer follows from requirements.json and the reference fixture: "
        "rerun scripts/resolve_models.py --apply and review the diff"
    )


@pytest.mark.parametrize(
    "requirements, fixture",
    [
        (ROLES / "requirements.json", FIXTURES / "resolver"),
        (FIXTURES / "resolver_small" / "requirements.json", FIXTURES / "resolver_small"),
    ],
    ids=["committed", "small"],
)
def test_every_named_model_takes_tool_calls_and_the_admitted_context(requirements, fixture):
    table = resolve_fixture(requirements, fixture)
    min_context = load(requirements)["common"]["min_context"]
    catalogue = {entry["id"]: entry for entry in load(fixture / "models.json")["data"]}
    named = named_models(table)
    assert named
    for preset, role, column, model in named:
        entry = catalogue[model]
        where = f"{preset} / {role} / {column}: {model}"
        assert REQUIRED_PARAMETERS <= set(entry.get("supported_parameters") or []), where
        assert entry.get("context_length", 0) >= min_context, where


def test_the_mrcall_column_carries_what_the_other_columns_carry():
    table = load(ROLES / "resolved.json")
    floors = load(ROLES / "requirements.json")["roles"]
    for outcome in table["presets"].values():
        for role, row in outcome["roles"].items():
            mrcall = row["mrcall"]
            if mrcall is None:
                continue
            assert set(row["anthropic_fallback"]) | {"id"} <= set(mrcall) | {"catalogue_price"}
            below = (
                floors[role].get("floor") is not None and mrcall["score"] < floors[role]["floor"]
            )
            assert mrcall["below_floor"] is below, role
    # The five floor-40 roles get Sonnet 5 (38.2) under economy, and it says so.
    economy = table["presets"]["economy"]["roles"]
    short = [r for r, row in economy.items() if row["mrcall"] and row["mrcall"]["below_floor"]]
    assert len(short) == 5 and all(floors[r].get("floor") == 40 for r in short)
