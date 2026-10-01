"""Fixture tests for the role resolver and its script.

`zylch/llm/roles/resolver.py` is ported from the kit's
`shared/scripts/resolve-models.py`; these cases reuse the kit's own tests where
they apply (the rules, the tie-breaks, the filters, the degrade paths, the
saved-run replay) and add the engine's extensions (the prefix exclusion, the
Anthropic fallback and its ceiling, the `mrcall` column, `--check`). They run
on `fixtures/llm/resolver_small/` (a dozen handcrafted entries shaped like the
real payloads) and once on the real fixture `fixtures/llm/resolver/`. No case
reaches the network or writes the engine's own `resolved.json`. The last case
is the one-time differential against the kit's script, skipped without it.
"""

import importlib.util
import io
import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from zylch.llm.roles import resolver

ENGINE = Path(__file__).resolve().parents[2]
SCRIPT = ENGINE / "scripts" / "resolve_models.py"
FIXTURES = ENGINE / "tests" / "fixtures" / "llm"
SMALL, REAL = FIXTURES / "resolver_small", FIXTURES / "resolver"
KIT = Path("/home/user/malemi/mrcall-ai-kit")
READ_AT = "2026-10-01T12:00:00Z"
PRICE_KEYS = (("input", "prompt"), ("output", "completion"))


def load_script():
    spec = importlib.util.spec_from_file_location("resolve_models_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = load_script()


def small_req() -> dict:
    return json.loads((SMALL / "requirements.json").read_text(encoding="utf-8"))


def raw(where: Path = SMALL) -> dict:
    return {
        "catalogue": (where / "models.json").read_bytes(),
        "benchmarks": (where / "benchmarks.json").read_bytes(),
        "read_at": (where / "read-at.txt").read_text(encoding="utf-8").strip(),
    }


def table(req: dict | None = None, payloads: dict | None = None) -> dict:
    req = small_req() if req is None else req
    return resolver.document(req, resolver.resolve(req, raw() if payloads is None else payloads))


def picks(doc: dict, column: str = "catalogue_id") -> dict:
    """{(preset, role): id} for the main pick or, with `fallback`, the fallback."""
    out = {}
    for preset, outcome in doc["presets"].items():
        for role, row in outcome["roles"].items():
            out[(preset, role)] = (
                row["anthropic_fallback"]["catalogue_id"] if column == "fallback" else row[column]
            )
    return out


def pool_ids(req: dict, payloads: dict | None = None) -> set:
    payloads = raw() if payloads is None else payloads
    catalogue, _ = resolver.payload_list(payloads["catalogue"], "catalogue")
    benchmarks, _ = resolver.payload_list(payloads["benchmarks"], "benchmarks")
    return {c["id"] for c in resolver.candidates(catalogue, benchmarks, req["common"])[0]}


# ------------------------------------------------------------ the rules


def test_the_rules_on_the_small_fixture():
    doc = table()
    assert picks(doc) == {
        ("economy", "SMART"): "vendor/wise-8",
        ("economy", "AGENT"): "vendor/agent-max",
        ("economy", "CHEAP"): "vendor/no-agentic",
        ("economy", "HIGHFLOOR"): "vendor/wise-8",
        ("balanced", "SMART"): "anthropic/claude-big-3.1",
        ("balanced", "AGENT"): "vendor/agent-max",
        ("balanced", "CHEAP"): "vendor/no-agentic",
        ("balanced", "HIGHFLOOR"): "anthropic/claude-big-3.1",
    }
    economy = doc["presets"]["economy"]
    assert economy["ceiling"] == 10 and economy["raised_to"] is None
    assert economy["roles"]["HIGHFLOOR"]["below_floor"] is True
    assert economy["roles"]["CHEAP"]["below_floor"] is False
    assert economy["roles"]["SMART"]["price"] == {"input": 1.6, "output": 8}
    assert economy["roles"]["SMART"]["scores"] == dict(intelligence=52, coding=None, agentic=None)
    assert doc["as_of"] == dict(benchmarks="2026-10-01T00:00:00.000Z", catalogue=READ_AT)


def c(model, price, score):
    scores = dict(intelligence=score, coding=None, agentic=None)
    return dict(id=model, price=Decimal(str(price)), input_price=None, scores=scores)


def test_maximise_tie_goes_to_the_cheaper_model():
    # The cheaper one sorts last by name, so only the price can choose it.
    pool = [c("v/a-dear", 3, 60), c("v/z-cheap", 2, 60)]
    rule = {"rule": "maximise", "index": "intelligence"}
    assert resolver.choose(rule, pool)[0]["id"] == "v/z-cheap"


def test_satisfice_tie_goes_to_the_higher_score_and_a_full_tie_to_the_id():
    rule = {"rule": "satisfice", "index": "intelligence", "floor": 40}
    pool = [c("v/a-41", 1, 41), c("v/z-47", 1, 47), c("v/dear", 5, 90)]
    assert resolver.choose(rule, pool) == (pool[1], False)
    assert resolver.choose(rule, [c("v/b", 1, 41), c("v/a", 1, 41)])[0]["id"] == "v/a"
    # Equal to the floor clears it; nothing clearing takes the best and says so.
    assert resolver.choose(rule, [c("v/x", 1, 40)])[1] is False
    assert resolver.choose(rule, [c("v/x", 1, 39), c("v/y", 2, 30)]) == (c("v/x", 1, 39), True)


# ---------------------------------------------------------- the filters


def test_the_prefix_exclusion_keeps_haiku_out_and_would_otherwise_win():
    req = small_req()
    assert "anthropic/claude-haiku-9" not in pool_ids(req)
    assert "anthropic/claude-haiku-9" not in picks(table(req)).values()
    req["common"]["excluded_prefixes"] = []
    assert picks(table(req))[("economy", "SMART")] == "anthropic/claude-haiku-9"


def test_variants_tools_context_and_required_scores_filter_the_pool():
    req = small_req()
    gone = {f"vendor/{m}" for m in "genius:free genius:batch no-tools short-context".split()}
    gone.add("vendor/no-intelligence")
    assert not gone & pool_ids(req)
    req["common"].update(excluded_variants=[], tools=False, min_context=100000, required_scores=[])
    assert gone <= pool_ids(req)


def test_a_none_score_leaves_only_that_index_pool():
    doc = table()
    # no-agentic wins CHEAP on intelligence and is never offered to AGENT.
    assert doc["presets"]["economy"]["roles"]["CHEAP"]["catalogue_id"] == "vendor/no-agentic"
    eligible = resolver.eligible_by_role(
        small_req()["roles"], resolver.resolve(small_req(), raw())["pool"], "test"
    )
    assert "vendor/no-agentic" not in {x["id"] for x in eligible["AGENT"]}
    assert "vendor/no-agentic" in {x["id"] for x in eligible["CHEAP"]}


def test_another_source_and_disagreeing_records_score_nothing():
    payloads = raw()
    bench = json.loads(payloads["benchmarks"])
    bench["data"].append({**bench["data"][7], "intelligence_index": 1})  # wise-8 disagrees
    bench["meta"].pop("model_count")
    payloads["benchmarks"] = json.dumps(bench).encode()
    result = resolver.resolve(small_req(), payloads)
    assert result["ambiguous"] == {"vendor/wise-8-20260101"}
    assert "vendor/wise-8" not in {x["id"] for x in result["pool"]}
    assert "vendor/cheap-41" in {x["id"] for x in result["pool"]}  # design-arena ignored


# ------------------------------------- the raise, the fallback, the ids


def test_the_ceiling_raise_and_raised_to():
    req = small_req()
    req["presets"] = {"tight": {"ceiling": 0.4}}
    tight = table(req)["presets"]["tight"]
    # No agentic score at or under 0.4: every role chooses under 0.5.
    assert tight["ceiling"] == 0.4 and tight["raised_to"] == 0.5
    assert tight["roles"]["AGENT"]["catalogue_id"] == "vendor/cheap-41"
    assert tight["roles"]["SMART"]["catalogue_id"] == "vendor/no-agentic"


def test_the_fallback_is_bounded_by_the_ceiling():
    fallback = picks(table(), "fallback")
    assert fallback[("economy", "SMART")] == "anthropic/claude-mid-2"
    assert fallback[("balanced", "SMART")] == "anthropic/claude-big-3.1"  # huge-4 is $25
    assert fallback[("balanced", "AGENT")] == "anthropic/claude-mid-2"  # big-3.1 unscored
    assert set(fallback.values()) <= {"anthropic/claude-mid-2", "anthropic/claude-big-3.1"}
    doc = table()
    assert doc["presets"]["economy"]["anthropic_raised_to"] is None
    assert doc["presets"]["balanced"]["roles"]["HIGHFLOOR"]["anthropic_fallback"]["below_floor"]


def test_the_fallback_raises_on_its_own():
    req = small_req()
    req["presets"] = {"five": {"ceiling": 5}, "open": {"ceiling": None}}
    doc = table(req)
    five = doc["presets"]["five"]
    assert five["raised_to"] is None and five["anthropic_raised_to"] == 10
    assert five["roles"]["SMART"]["anthropic_fallback"]["catalogue_id"] == "anthropic/claude-mid-2"
    unbounded = doc["presets"]["open"]["roles"]["SMART"]["anthropic_fallback"]
    assert unbounded["catalogue_id"] == "anthropic/claude-huge-4"


def test_a_billed_price_above_the_catalogue_s_is_the_one_a_ceiling_compares():
    req = small_req()  # agent-max lists at $6 and, like K3, is billed above that
    row = {"transport": "openrouter", "price": dict(input="3", output="12")}
    req["allowlist"]["vendor/agent-max"] = row
    doc = table(req)
    assert doc["presets"]["economy"]["roles"]["AGENT"]["catalogue_id"] == "anthropic/claude-mid-2"
    balanced = doc["presets"]["balanced"]["roles"]["AGENT"]
    assert balanced["catalogue_id"] == "vendor/agent-max"
    assert balanced["price"] == {"input": 3, "output": 12}
    assert balanced["catalogue_price"] == {"input": 1.2, "output": 6}
    assert "catalogue_price" not in doc["presets"]["balanced"]["roles"]["SMART"]


def test_direct_ids():
    assert resolver.direct_id("anthropic/claude-sonnet-5") == "claude-sonnet-5"
    assert resolver.direct_id("anthropic/claude-opus-5.5") == "claude-opus-5-5"
    assert resolver.direct_id("z-ai/glm-5.3") is None
    assert resolver.served_id("moonshotai/kimi-k3") == "moonshotai/kimi-k3"
    for outcome in table()["presets"].values():
        for row in outcome["roles"].values():
            assert row["direct_id"] == resolver.direct_id(row["catalogue_id"])


def mrcall(served, presets=None):
    req = small_req()
    req["mrcall_served"] = served
    req["presets"] = presets or req["presets"]
    doc = table(req)
    rows = {k: doc["presets"][k[0]]["roles"][k[1]]["mrcall"] for k in picks(doc)}
    return doc, {k: row and row["id"] for k, row in rows.items()}


def test_the_mrcall_column_is_chosen_over_the_served_subset():
    doc, ids = mrcall(["claude-mid-2"])
    # The fallback takes big-3.1 at $20; the server serves only mid-2.
    assert doc["presets"]["balanced"]["roles"]["SMART"]["anthropic_fallback"]["direct_id"] == (
        "claude-big-3-1"
    )
    assert set(ids.values()) == {"claude-mid-2"}
    doc, ids = mrcall(["claude-mid-2", "vendor/agent-max"])  # a served non-Anthropic id
    assert ids[("economy", "SMART")] == ids[("economy", "AGENT")] == "vendor/agent-max"
    assert ids[("economy", "CHEAP")] == "vendor/agent-max"  # $6 clears 40, mid-2 is $10
    assert ids[("balanced", "SMART")] == "vendor/agent-max"  # 45 beats mid-2's 40
    assert doc["presets"]["economy"]["mrcall_raised_to"] is None


def test_a_role_no_served_model_fits_is_null_and_takes_no_part_in_the_raise(rig, capsys):
    doc, ids = mrcall(["claude-big-3-1"])
    # big-3.1 has no agentic score: AGENT is null, not refused.
    assert ids[("economy", "AGENT")] is None and ids[("balanced", "AGENT")] is None
    assert ids[("economy", "SMART")] == "claude-big-3-1"
    economy = doc["presets"]["economy"]
    assert economy["mrcall_raised_to"] == 20 and economy["raised_to"] is None
    assert doc["presets"]["balanced"]["mrcall_raised_to"] is None
    run, _, req_path = rig
    req = small_req()
    req["mrcall_served"] = ["claude-big-3-1"]
    req_path.write_text(json.dumps(req), encoding="utf-8")
    assert run("--fixture", str(SMALL)) == 0
    out = capsys.readouterr().out
    assert "not served by credits" in out and "mrcall raised to $20" in out


# ---------------------------------------------------------- the refusals


def test_refused_on_no_candidate_and_on_a_missing_index():
    req = small_req()
    req["common"]["min_context"] = 10**9
    with pytest.raises(resolver.Refused, match="no candidate at any price for SMART"):
        resolver.resolve(req, raw())
    req = small_req()
    req["roles"]["CODER"] = {"rule": "maximise", "index": "coding"}
    payloads = raw()
    bench = json.loads(payloads["benchmarks"])
    for record in bench["data"]:
        record["coding_index"] = None
    payloads["benchmarks"] = json.dumps(bench).encode()
    with pytest.raises(resolver.Refused, match="every vendor: no candidate .* CODER"):
        resolver.resolve(req, payloads)


def test_refused_when_the_anthropic_subset_cannot_serve_a_role():
    payloads = raw()
    bench = json.loads(payloads["benchmarks"])
    for record in bench["data"]:
        if record["model_permaslug"].startswith("anthropic/"):
            record["agentic_index"] = None
    payloads["benchmarks"] = json.dumps(bench).encode()
    with pytest.raises(resolver.Refused, match="the Anthropic fallback: .* AGENT"):
        resolver.resolve(small_req(), payloads)


UNREADABLE = [(None, "no payload"), (b"<html>502</html>", "not JSON")]
UNREADABLE += [
    (b'{"error": "unauthorized"}', "missing or empty"),
    (b'{"data": []}', "missing or empty"),
]


@pytest.mark.parametrize("body, says", UNREADABLE)
def test_refused_on_an_unreadable_payload(body, says):
    payloads = raw()
    payloads["benchmarks"] = body
    with pytest.raises(resolver.Refused, match=says):
        resolver.resolve(small_req(), payloads)


# ----------------------------------------------------------- the script


@pytest.fixture
def rig(tmp_path):
    """A requirements file and a resolved.json path of its own."""
    req = tmp_path / "requirements.json"
    req.write_text((SMALL / "requirements.json").read_text(encoding="utf-8"), encoding="utf-8")
    resolved = tmp_path / "resolved.json"

    def run(*args):
        return script.main(list(args), requirements_path=req, resolved_path=resolved)

    return run, resolved, req


def test_apply_guard_save_replay_and_check(rig, tmp_path, capsys):
    run, resolved, _ = rig
    assert run("--fixture", str(SMALL), "--save", str(tmp_path / "saved")) == 0
    assert not resolved.exists()  # no --apply, nothing written
    assert "nothing written" in capsys.readouterr().out
    assert run("--fixture", str(SMALL), "--check") == 1  # no committed table
    assert run("--fixture", str(tmp_path / "saved"), "--apply") == 0
    written = resolved.read_bytes()
    assert json.loads(written) == table()
    for name in ("models.json", "benchmarks.json", "read-at.txt"):
        assert (tmp_path / "saved" / name).read_bytes() == (SMALL / name).read_bytes()
    assert run("--fixture", str(SMALL), "--check") == 0
    assert run("--fixture", str(SMALL)) == 0 and resolved.read_bytes() == written
    drifted = json.loads(written)
    drifted["presets"]["economy"]["roles"]["SMART"]["catalogue_id"] = "vendor/agent-max"
    resolved.write_text(json.dumps(drifted), encoding="utf-8")
    capsys.readouterr()
    assert run("--fixture", str(SMALL), "--check") == 1
    assert "economy / SMART: vendor/agent-max -> vendor/wise-8" in capsys.readouterr().out


def test_an_unreadable_source_exits_1_and_leaves_the_table(rig, tmp_path, capsys):
    run, resolved, _ = rig
    resolved.write_text('{"kept": "byte for byte"}\n', encoding="utf-8")
    fixture = tmp_path / "fx"
    fixture.mkdir()
    (fixture / "models.json").write_bytes((SMALL / "models.json").read_bytes())
    assert run("--fixture", str(fixture), "--apply") == 1
    assert "benchmarks.json: no such file" in capsys.readouterr().err
    for body in (b"<html>502</html>", b'{"data": []}'):
        (fixture / "benchmarks.json").write_bytes(body)
        assert run("--fixture", str(fixture), "--apply") == 1
        assert "resolved.json is unchanged" in capsys.readouterr().err
    assert resolved.read_text(encoding="utf-8") == '{"kept": "byte for byte"}\n'


def test_a_config_error_exits_2(rig):
    run, resolved, req = rig
    bad = small_req()
    del bad["allowlist"]
    req.write_text(json.dumps(bad), encoding="utf-8")
    assert run("--fixture", str(SMALL), "--apply") == 2 and not resolved.exists()
    with pytest.raises(SystemExit) as exit_:
        run("--apply", "--check")
    assert exit_.value.code == 2


def test_the_key_comes_from_the_environment_only(rig, tmp_path, monkeypatch, capsys):
    run, resolved, _ = rig
    seen = {}

    def urlopen(request, timeout):
        seen[request.full_url] = request.get_header("Authorization")
        name = "models.json" if request.full_url.endswith("/models") else "benchmarks.json"
        return io.BytesIO((SMALL / name).read_bytes())  # read() and a context

    monkeypatch.setattr(script.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv(script.API_ENV, "http://openrouter.test/api/v1")
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=from-a-file\n", encoding="utf-8")
    monkeypatch.delenv(script.KEY_ENV, raising=False)
    assert run("--apply") == 1 and not seen and not resolved.exists()
    assert "OPENROUTER_API_KEY is not set" in capsys.readouterr().err
    monkeypatch.setenv(script.KEY_ENV, "from-the-environment")
    assert run("--apply") == 0
    assert seen == {
        "http://openrouter.test/api/v1/models": None,
        "http://openrouter.test/api/v1/benchmarks": "Bearer from-the-environment",
    }
    assert "from-the-environment" not in resolved.read_text(encoding="utf-8")


# ------------------------------------------------------- the real data


def test_the_committed_requirements_carry_the_roster_and_today_s_prices():
    from .test_price_source import TODAY_DIRECT as PRICES
    from .test_price_source import TODAY_OPENROUTER as RATES

    req = resolver.validate_requirements(
        json.loads((script.REQUIREMENTS).read_text(encoding="utf-8"))
    )
    roster = "MNEMONIC MEMORY_EXTRACT MEMORY_MERGE TASK_DETECTION REANALYZE DEDUP REPLY_NEED"
    roster += " INTENT CHAT TASK_SOLVE TRAIN COMPACTION SYNC_ANALYSIS WEB_SEARCH"
    assert list(req["roles"]) == (roster + " CORRECTION_LEARNING NARRATION").split()
    assert req["common"]["excluded_prefixes"] == ["anthropic/claude-haiku"]
    assert {k: v["ceiling"] for k, v in req["presets"].items()} == {"economy": 10, "balanced": 20}
    allow = req["allowlist"]
    billed = {m: ("direct", p) for m, p in PRICES.items()}
    billed.update({m: ("openrouter", p) for m, p in RATES.items()})
    for model, (transport, (i, o)) in billed.items():
        price = allow[model]["price"]
        assert allow[model]["transport"] == transport, model
        assert (Decimal(price["input"]), Decimal(price["output"])) == (i, o), model
    assert len(allow) == len(PRICES) + len(RATES)
    assert allow["moonshotai/kimi-k3"]["reasoning_contract"] == "k3"
    haiku = [m for m in allow if "haiku" in m]
    assert all("never a default or an arm" in allow[m]["note"] for m in haiku) and len(haiku) == 3
    assert set(req["mrcall_served"]) == set(PRICES) | {"moonshotai/kimi-k3"}
    real = {e["id"]: e["pricing"] for e in json.loads(raw(REAL)["catalogue"])["data"]}
    for model, row in allow.items():  # informational: today's catalogue beside the billed price
        if row["transport"] == "openrouter":
            listed = {k: resolver.per_million(real[model][v]) for k, v in PRICE_KEYS}
            assert {k: Decimal(row["catalogue_price"][k]) for k in listed} == listed, model


def test_the_real_fixture_resolves_and_haiku_is_in_no_pool():
    req = json.loads(script.REQUIREMENTS.read_text(encoding="utf-8"))
    payloads = raw(REAL)
    catalogue = json.loads(payloads["catalogue"])["data"]
    assert any(e["id"].startswith("anthropic/claude-haiku") for e in catalogue)
    result = resolver.resolve(req, payloads)
    assert not [x for x in result["pool"] if x["id"].startswith("anthropic/claude-haiku")]
    text = json.dumps(resolver.document(req, result))
    assert "haiku" not in text
    loosened = json.loads(json.dumps(req))
    loosened["common"]["excluded_prefixes"] = []
    assert "anthropic/claude-haiku-4.5" in pool_ids(loosened, payloads)


def test_the_script_runs_from_any_directory_without_writing(tmp_path):
    before = script.RESOLVED.read_bytes() if script.RESOLVED.exists() else None
    env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}
    run = subprocess.run(
        [sys.executable, str(SCRIPT), "--fixture", str(REAL)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert run.returncode == 0, run.stderr
    assert "economy: ceiling $10" in run.stdout and "nothing written" in run.stdout
    assert (script.RESOLVED.read_bytes() if script.RESOLVED.exists() else None) == before


# --------------------------------------------- the differential with the kit


@pytest.mark.skipif(
    not (KIT / "shared/scripts/resolve-models.py").is_file(), reason="the kit's checkout is absent"
)
def test_the_port_reproduces_the_kit_on_the_kit_s_rules():
    """The kit's `claude` runtime is the port's Anthropic fallback; its
    `opencode` runtime (unfiltered by `opencode models`) is the port's main
    pick. Same fixture, the kit's requirements, every budget and role."""
    spec = importlib.util.spec_from_file_location(
        "kit_resolver", KIT / "shared/scripts/resolve-models.py"
    )
    kit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kit)
    kit_req = kit.load_requirements(KIT / "shared/roles/requirements.json")
    kit_doc = kit.document(kit_req, kit.resolve(kit_req, kit.read_sources(REAL)))["runtimes"]
    for runtime, column in (("claude", "fallback"), ("opencode", "catalogue_id")):
        spec_rt = kit_req["runtimes"][runtime]
        port_req = {
            "common": {**kit_req["common"], "excluded_prefixes": []},
            "presets": {b: {"ceiling": v} for b, v in spec_rt["ceilings"].items()},
            "roles": spec_rt["roles"],
            "allowlist": {},
            "mrcall_served": [],
        }
        doc = table(resolver.validate_requirements(port_req), raw(REAL))
        theirs = {
            (b, r): row["catalogue_id"]
            for b, o in kit_doc[runtime].items()
            for r, row in o["roles"].items()
        }
        assert picks(doc, column) == theirs, runtime
        for budget, outcome in kit_doc[runtime].items():
            raised = "anthropic_raised_to" if runtime == "claude" else "raised_to"
            assert doc["presets"][budget][raised] == outcome["raised_to"]
