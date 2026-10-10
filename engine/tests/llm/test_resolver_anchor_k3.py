"""The half rule and the pinned endpoint (`candidates.keeps_level`, `anchored`).

The model-level price is the reference only when at least half the eligible
endpoints (⌈n / 2⌉ of n) are priced within it × the margin. On the live read
of 2026-10-10 12:01Z OpenRouter showed K3 at 0.64/13.5, its fp4 outlier's
price; two oddly priced eligible endpoints (`wafer` 0.33/14.89, `morph/fp8`
0.339/14.9) fit under 0.8 on input, so "at least one" kept that price, admitted
only those two and dropped K3's pinned `digitalocean` (2.55/12.95): its cap
fell back to 0.64/13.5 × the margin, under the pin's own input, and every
production K3 request would have been refused by `max_price`. Under the half
rule two of twelve fall back to the lower median (2.8/14), and the pinned
endpoint (`requirements.json` `provider_policy.pinned_endpoints`) is admitted
whenever it is eligible, whatever the reference, so K3's cap is always its
pin's price × the margin while the pin is up.
"""

from __future__ import annotations

from decimal import Decimal

from zylch.llm import k3_reasoning
from zylch.llm.openrouter_pricing import capped
from zylch.llm.roles import candidates, catalogue, snapshot

from .resolver_fixture import K3, by_id, requirements, sources
from .test_resolver_anchor import listed_at, priced, rules

D = Decimal
# K3's eligible endpoints on 2026-10-10 12:01Z (and its fp4 outlier, not
# eligible), as (tag, input, output, quantization) per million.
K3_20261010 = (
    ("wafer", "0.33", "14.89", "unknown"),
    ("morph/fp8", "0.339", "14.9", "fp8"),
    ("inference-net/fp4", "0.64", "13.5", "fp4"),
    ("phala", "2.55", "12.75", "unknown"),
    ("digitalocean", "2.55", "12.95", "unknown"),
    ("together", "2.7", "13.5", "unknown"),
    ("wafer/us", "2.8", "14", "unknown"),
    ("amazon-bedrock/us-east-2", "3", "15", "unknown"),
    ("fireworks", "3", "15", "unknown"),
    ("baseten/fp8", "3", "15", "fp8"),
    ("alibaba", "3.45", "17.25", "unknown"),
    ("fireworks/us", "4.5", "22.5", "unknown"),
    ("fireworks/fast", "4.5", "22.5", "unknown"),
)


def k3_on_20261010() -> tuple[dict, list[dict]]:
    entry = dict(by_id(sources()["catalogue"])[K3])
    entry["pricing"] = listed_at("0.64", "13.5", cache_read="0.28")["pricing"]
    listed = [priced(tag, i, o, quantization=q) for tag, i, o, q in K3_20261010]
    return entry, listed


def tags(endpoints: list[dict]) -> list[str]:
    return [e["tag"] for e in endpoints]


def test_the_pin_is_k3_s_endpoint():
    assert rules()["pinned_endpoints"] == {k3_reasoning.MODEL: k3_reasoning.ENDPOINT}


def test_k3_on_2026_10_10_falls_back_and_keeps_its_pin_and_its_cap():
    entry, listed = k3_on_20261010()
    rows = candidates.eligible(listed, rules())
    level = candidates.prices_of(entry["pricing"])
    assert len(rows) == 12
    assert [e["tag"] for e, p in rows if candidates.fits(p, level, D("1.25"))] == [
        "wafer",
        "morph/fp8",
    ]
    price, admitted = candidates.anchored(entry, listed, rules())
    assert (price["input"], price["output"]) == (D("2.8"), D(14))  # wafer/us, the lower median
    assert "digitalocean" in tags(admitted) and len(admitted) == 10
    built = snapshot.build([entry], {K3: listed}, rules(), "2026-10-10T12:01:52Z")
    catalogue.set_layers(built, build=False)
    try:
        assert k3_reasoning.rates() == (D("2.55"), D("12.95"))
        assert capped(K3) == (D("3.1875"), D("16.1875"))
        assert k3_reasoning.provider_policy()["max_price"] == {
            "prompt": "3.1875",
            "completion": "16.1875",
            "request": "0",
        }
    finally:
        catalogue.set_layers()


def test_a_list_price_admitting_2_of_12_falls_back():
    listed = [priced(f"odd{n}", "0.5", "5") for n in range(2)]
    listed += [priced(f"main{n:02}", "2", "10") for n in range(10)]
    price, admitted = candidates.anchored(listed_at("1", "10"), listed, rules())
    assert (price["input"], price["output"]) == (D(2), D(10))
    assert admitted == listed


def test_a_list_price_admitting_6_of_12_is_kept():
    # Six fit under 1/10 × 1.25 (1.2/12), six do not (2/12): the list price
    # stays, though the lower median would be 1.2/12.
    listed = [priced(f"near{n}", "1.2", "12") for n in range(6)]
    listed += [priced(f"dear{n}", "2", "12") for n in range(6)]
    assert candidates.reference(candidates.eligible(listed, rules()))[1]["input"] == D("1.2")
    price, admitted = candidates.anchored(listed_at("1", "10"), listed, rules())
    assert (price["input"], price["output"]) == (D(1), D(10))
    assert admitted == listed[:6]
    # Five of twelve is fewer than half: the lower median, a dear one.
    fewer = [priced(f"near{n}", "1.2", "12") for n in range(5)]
    fewer += [priced(f"dear{n}", "2", "12") for n in range(7)]
    price, admitted = candidates.anchored(listed_at("1", "10"), fewer, rules())
    assert (price["input"], price["output"]) == (D(2), D(12)) and admitted == fewer


def test_the_pin_is_admitted_when_eligible_though_an_outlier_reference_prices_it_out():
    entry, listed = k3_on_20261010()
    pin = next(e for e in listed if e["tag"] == "digitalocean")
    # Thirteen cheap eligible endpoints of 25 keep a list price of 1/5: the
    # pin's 2.55 is above 1.25, yet it is admitted, and only it among the dear.
    cheap = [priced(f"cheap{n:02}", "1", "5") for n in range(13)]
    entry = {**entry, **{"pricing": listed_at("1", "5")["pricing"]}}
    price, admitted = candidates.anchored(entry, [*cheap, *listed], rules())
    assert (price["input"], price["output"]) == (D(1), D(5))
    assert not candidates.fits(candidates.prices_of(pin["pricing"]), price, D("1.25"))
    assert tags(admitted) == [*tags(cheap), "digitalocean"]
    # Another model with the same endpoints: the pin is K3's alone.
    other = {**entry, "id": "vendor/other"}
    assert "digitalocean" not in tags(candidates.anchored(other, [*cheap, *listed], rules())[1])
    # A pin that is not eligible (down when read) is never admitted.
    down = [*cheap, *[{**e, "status": -2} if e is pin else e for e in listed]]
    assert "digitalocean" not in tags(candidates.anchored(entry, down, rules())[1])
    # Requirements without pins admit by price alone.
    unpinned = {**rules(), "pinned_endpoints": {}}
    assert "digitalocean" not in tags(candidates.anchored(entry, [*cheap, *listed], unpinned)[1])
    assert requirements()["provider_policy"]["pinned_endpoints"] == {K3: "digitalocean"}
