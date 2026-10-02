"""The one-time differential of 10a's resolver port against the kit's script.

Moved from `test_resolver.py` with 10a's resolver (`resolver_10a.py`) when
resolver v2 replaced it (milestone 10, slice S2): the port it proves is the
10a mechanism v2 builds on, and the frozen `resolved.json` still comes from
it until the switch-over. It runs the kit's `shared/scripts/resolve-models.py`
and the port on the 2026-10-01 fixture (`fixtures/llm/resolver/`) under the
kit's own requirements, and is skipped where the kit's checkout is absent.
"""

import importlib.util
from pathlib import Path

import pytest

from . import resolver_10a as resolver

ENGINE = Path(__file__).resolve().parents[2]
REAL = ENGINE / "tests" / "fixtures" / "llm" / "resolver"
KIT = Path("/home/user/malemi/mrcall-ai-kit")


def raw(where: Path = REAL) -> dict:
    return {
        "catalogue": (where / "models.json").read_bytes(),
        "benchmarks": (where / "benchmarks.json").read_bytes(),
        "read_at": (where / "read-at.txt").read_text(encoding="utf-8").strip(),
    }


def table(req: dict, payloads: dict) -> dict:
    return resolver.document(req, resolver.resolve(req, payloads))


def picks(doc: dict, column: str = "catalogue_id") -> dict:
    """{(preset, role): id} for the main pick or, with `fallback`, the fallback."""
    out = {}
    for preset, outcome in doc["presets"].items():
        for role, row in outcome["roles"].items():
            out[(preset, role)] = (
                row["anthropic_fallback"]["catalogue_id"] if column == "fallback" else row[column]
            )
    return out


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
