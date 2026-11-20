"""The table the engine runs on, tied to its fixture and to the requirements in force (milestone 10 S6; D10).

Replaces 10a's `test_resolved_table.py`, which tied `roles/resolved.json` to
the fixture it was resolved from; `resolved.json` is gone at the switch-over.
The engine now runs on the published decision record `table.json`
(`roles/table.py`): downloaded and re-checked at run time
(`test_distribution.py`), else the build copy beside the code, which
`scripts/resolve_models.py --apply` writes only once `roles/measured.json`
covers every role and `release.yml` refreshes from the data branch. This
file ties both tables to their inputs:

- the fixture table every test resolves from (`fixtures/llm/model-table/`) is
  what `model_table_fixture.build()` gives from the 2026-10-02 capture and the
  committed requirements — never a hand edit — and passes every static gate
  against the requirements in force, so a role, a ceiling or an excluded
  family changed in `requirements.json` without the fixture fails here;
- the build copy is absent only while `measured.json` does not cover every
  role, and once present it passes every gate against the requirements in
  force and the build snapshot; at run time a build copy that fails a gate is
  not used (every pick then pauses rather than guessing);
- every model the fixture table ranks is priced by the one price source on its
  transport and admits a request, so a ranked model never pauses as unpriced.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from zylch.llm import budget_pricing, openrouter_pricing
from zylch.llm.roles import catalogue, gates, prices, table

from . import model_table_fixture as fixture

ROLES = Path(table.__file__).resolve().parent
BUILD_TABLE, MEASURED = ROLES / "table.json", ROLES / "measured.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["snapshot.json", "table.json"])
def test_the_fixture_is_what_the_builder_gives(name):
    built = fixture.build()[name]
    assert fixture.doc(name) == built, (
        f"tests/fixtures/llm/model-table/{name} no longer follows from the capture and "
        "requirements.json: regenerate it (python -m tests.llm.model_table_fixture) and review"
    )
    assert (fixture.FIXTURE / name).read_text(encoding="utf-8") == fixture.text(name, built)


def test_the_fixture_passes_every_gate_against_the_requirements_in_force():
    snapshot, record = fixture.doc("snapshot.json"), fixture.doc("table.json")
    gates.check_snapshot(snapshot)
    gates.check_table(record, load(ROLES / "requirements.json"), snapshot)
    gates.check_table_standalone(record, snapshot)
    in_force = load(ROLES / "requirements.json")
    for preset, body in record["presets"].items():
        assert set(body["roles"]) == set(in_force["roles"]), preset  # the file sorts its keys
        assert body["ceiling"] == str(in_force["presets"][preset]["ceiling"]), preset


def test_the_fixture_snapshot_is_cut_from_the_capture():
    capture, cut = fixture._capture(), fixture.doc("snapshot.json")
    assert cut["read_at"] == capture["read_at"] and cut["policy"] == capture["policy"]
    for model, row in cut["models"].items():
        assert row == capture["models"][model], model
    for model, row in cut["direct"].items():
        assert row == capture["direct"][model], model


def test_the_fixture_snapshot_agrees_with_the_price_fixture():
    """Both fixtures are cuts of the same capture by the same builder (S3's
    `snapshot-2026-10-02.json` for the price tests): a row they share is equal."""
    from . import price_fixture

    cut, prices_cut = fixture.doc("snapshot.json"), price_fixture.fixture()
    assert cut["read_at"] == prices_cut["read_at"] and cut["policy"] == prices_cut["policy"]
    shared = 0
    for section in ("models", "direct"):
        for model, row in cut[section].items():
            if model in prices_cut[section]:
                assert row == prices_cut[section][model], (section, model)
                shared += 1
    assert shared >= len(cut["models"]) - 1  # every model but the Haiku alias


def test_the_build_table_exists_once_measured_and_passes_every_gate_in_force():
    # A role is covered when measured.json lists it, as resolver.rankings reads it.
    roster = set(load(ROLES / "requirements.json")["roles"])
    covered = MEASURED.is_file() and roster <= set(load(MEASURED).get("roles") or {})
    if not BUILD_TABLE.is_file():
        assert not covered, (
            "measured.json covers every role but no table.json was written: "
            "run scripts/resolve_models.py --apply and review the table (the "
            "switch-over commits both; a role that ranks nothing blocks it)"
        )
        return
    record = load(BUILD_TABLE)
    gates.check_table(record, load(ROLES / "requirements.json"), load(ROLES / "snapshot.json"))
    table._build.cache_clear()
    try:
        assert table._build() == record  # the reader takes the build copy as it is
    finally:
        table._build.cache_clear()


@pytest.mark.parametrize(
    "breaks",
    [
        lambda r: r["presets"]["economy"].update(ceiling="11"),  # a raised ceiling
        lambda r: r["presets"]["balanced"]["roles"].pop("DEDUP"),  # an uncovered role
        lambda r: r["presets"]["economy"]["roles"]["CHAT"]["ranking"].insert(
            0, {"id": fixture.HAIKU, "direct_id": "claude-haiku-4-5"}
        ),
    ],
    ids=["raised-ceiling", "uncovered-role", "excluded-family"],
)
def test_a_build_copy_that_fails_a_gate_is_not_used(monkeypatch, tmp_path, breaks):
    snapshot, record = fixture.doc("snapshot.json"), copy.deepcopy(fixture.doc("table.json"))
    good = tmp_path / "good.json"
    good.write_text(json.dumps(record))
    breaks(record)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(gates.stamped(record)))
    monkeypatch.setattr(catalogue, "_build", lambda: snapshot)
    table.set_table(None)
    try:
        for path, used in ((good, True), (bad, False)):
            monkeypatch.setattr(table, "BUILD", path)
            table._build.cache_clear()
            assert (table.document() is not None) is used, path.name
        with pytest.raises(budget_pricing.BudgetError, match="no valid model table"):
            table.pick("economy", "CHAT", "openrouter")
    finally:
        table._build.cache_clear()


def _ranked_on_transports():
    record = fixture.doc("table.json")
    pairs = set()
    for body in record["presets"].values():
        for rankings in body["roles"].values():
            for column in ("ranking", "anthropic_ranking"):
                for entry in rankings[column]:
                    pairs.add((entry["id"], "openrouter"))
                    if entry["direct_id"]:
                        pairs.add((entry["direct_id"], "direct"))
    return sorted(pairs)


@pytest.mark.parametrize("model, transport", _ranked_on_transports())
def test_every_ranked_model_is_priced_on_its_transport_and_admits_a_request(model, transport):
    catalogue.set_layers(fixture.doc("snapshot.json"))  # the fixture's prices, wherever read
    rate = prices.price(model, transport)
    assert rate is not None and rate[0] > 0 and rate[1] > 0, (model, transport)
    request = {"model": model, "max_tokens": 64, "messages": [{"role": "user", "content": "x"}]}
    bound = (
        budget_pricing.request_bound(request, "direct")
        if transport == "direct"
        else openrouter_pricing.request_bound(request)
    )
    assert bound > 0
