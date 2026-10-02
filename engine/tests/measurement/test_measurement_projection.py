"""``measure_roles.py --project``: the free projection prices what the engine would reserve and send.

- the maximum of an arm is the engine's own reservation bound of the request
  the client would send for each case: for K3, its adapter's 8,192 output
  tokens at max effort, whatever ``max_tokens`` the call site asked for;
- the expected spend is positive and below the maximum;
- the report gives the totals, the D7 order with the cumulative expected spend
  and IR2's comparison with the cap less 20 %.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import measurement_common as common  # noqa: E402
import measurement_projection as projection  # noqa: E402
from measurement_runtime import RoleRun  # noqa: E402

K3 = "moonshotai/kimi-k3"
SONNET = "anthropic/claude-sonnet-5.5"
ARMS = [
    {"id": K3, "score": 43.6, "index": "intelligence", "reference": True},
    {"id": SONNET, "score": 56.0, "index": "intelligence", "reference": False},
]


def reply_need():
    document = common.load_document("REPLY_NEED")
    document["cases"] = document["cases"][:3]
    return RoleRun("REPLY_NEED", document, common.load_requests("REPLY_NEED"), ARMS)


def test_k3_s_maximum_reserves_its_adapter_s_output_cap_on_every_case():
    from zylch.llm.roles.prices import price

    run = reply_need()
    cases, maximum, expected, fallback = projection.role_arm(run, K3)
    _input_rate, output_rate = price(K3, "openrouter")
    floor = Decimal(cases * 8192) * output_rate / Decimal(1_000_000)
    assert cases == 3 and not fallback
    assert maximum > floor  # 8,192 tokens, not the call site's 2,000
    assert Decimal(0) < expected < maximum


def test_a_shaped_arm_is_bound_on_the_request_the_client_sends():
    run = reply_need()
    _cases, maximum, expected, _fallback = projection.role_arm(run, SONNET)
    entry = run.entry(run.document["cases"][0]["id"])
    sent = common.reserved_request(
        projection.client_for(SONNET), **{**entry["request"], "model": SONNET}
    )
    assert sent["max_tokens"] == entry["request"]["max_tokens"] + 1024  # reasoning headroom
    assert Decimal(0) < expected < maximum


def test_the_report_gives_totals_the_priority_order_and_ir2(capsys):
    assert projection.main([reply_need()], {}, Decimal("20"), corpus_roles=False) == 0
    out = capsys.readouterr().out
    assert "total: maximum USD" in out and "D7 priority, cumulative expected spend" in out
    assert "the reference second repetition" in out
    assert "IR2: expected one repetition" in out and "USD 16.0 (the cap less 20 %)" in out
