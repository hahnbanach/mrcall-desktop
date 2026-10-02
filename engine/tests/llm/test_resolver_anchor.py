"""The price anchor: the reference endpoint and the reference price (`candidates.anchored`).

OpenRouter computes a model's model-level price over every endpoint, those
the provider policy excludes included, and moves it at its own discretion:
on the live read of 2026-10-02 17:24Z GLM 5.3 Flash's model-level price was
its fp4 endpoint's (0.02625/0.9), below every 8-bit or undeclared endpoint,
so none was admitted. The anchor is the reference endpoint instead — the
lower median, index (n - 1) // 2, of the eligible endpoints (up, an allowed
quantization, tools, no excluded tier, a fixed price) ordered by Artificial
Analysis's blended price (3 × input + output) / 4, a tie by output, then
input, then tag. Its price is the model's reference price, which the
snapshot publishes and the ceilings compare, and an eligible endpoint is
admitted at or under it × the margin, the reference itself always. The
model-level price stays the price of a model whose endpoints were not read
or have none eligible. Each case isolates one of these rules, on the
2026-10-02 capture where it shows one and on synthetic endpoints otherwise.
"""

from __future__ import annotations

from decimal import Decimal

from zylch.llm.roles import candidates, snapshot

from .resolver_fixture import OPUS, by_id, endpoint, entry, requirements, sources

D = Decimal
GLM_FLASH, ALL_FP4 = "z-ai/glm-5.3-flash", "poolside/laguna-s-2.1"
SUB_8_BIT = ("fp4", "nvfp4", "mxfp4", "int4", "fp6")


def per_token(price: str) -> str:
    """A price per million tokens as the payloads write it, per token."""
    return format(D(price) / candidates.MILLION, "f")


def priced(tag: str, input_price: str, output_price: str, **fields) -> dict:
    """An eligible endpoint at `input_price`/`output_price` per million."""
    pricing = {"prompt": per_token(input_price), "completion": per_token(output_price)}
    return endpoint(tag, pricing=pricing, **fields)


def rules(margin: str | None = None) -> dict:
    policy = candidates.policy(requirements())
    return {**policy, "margin": D(margin)} if margin else policy


def test_a_model_level_price_set_by_an_fp4_outlier_keeps_the_model_routable():
    src = sources()
    glm, listed = by_id(src["catalogue"])[GLM_FLASH], src["endpoints"][GLM_FLASH]
    fp4 = next(e for e in listed if e["tag"] == "open-inference/fp4")
    # The live read's model-level price: its fp4 endpoint's.
    live = {
        **glm,
        "pricing": {**glm["pricing"], **{k: fp4["pricing"][k] for k in ("prompt", "completion")}},
    }
    assert candidates.model_price(live) == (D("0.02625"), D("0.9"))
    price, admitted = candidates.anchored(live, listed, rules())
    assert (price["input"], price["output"]) == (D("0.15"), D("0.5"))
    assert len(admitted) == 20 and fp4 not in admitted
    assert not [e for e in admitted if candidates.quantization(e) in SUB_8_BIT]
    # Anchored at that model-level price, no endpoint would be admitted.
    cap = (D("0.02625") * D("1.25"), D("0.9") * D("1.25"))
    eligible = candidates.eligible(listed, rules())
    assert not [e for e, p in eligible if p["input"] <= cap[0] and p["output"] <= cap[1]]
    # The same shape on four endpoints.
    model = entry(pricing={"prompt": per_token("0.02625"), "completion": per_token("0.9")})
    outlier = priced("outlier/fp4", "0.02625", "0.9", quantization="fp4")
    rest = [priced(f"p{n}/fp8", "0.15", "0.5") for n in range(2)]
    rest.append(priced("p2", "0.1", "0.4", quantization=None))
    price, admitted = candidates.anchored(model, [outlier, *rest], rules())
    assert (price["input"], price["output"]) == (D("0.15"), D("0.5")) and admitted == rest


def test_an_anti_correlated_pair_admits_its_reference():
    a, b = priced("vendor-a", "0.1", "1.0"), priced("vendor-b", "0.3", "0.2")
    price, admitted = candidates.anchored(entry(), [a, b], rules())
    # Blended, B (0.275) is under A (0.325): the lower median of two is B.
    assert (price["input"], price["output"]) == (D("0.3"), D("0.2"))
    assert admitted == [b]  # A's output, 1.0, is above 0.2 x 1.25


def test_the_reference_is_the_lower_median_a_tie_by_output_then_input_then_tag():
    rows = [
        priced("z-out", "0.3", "0.1"),
        priced("b-mid", "0.2", "0.4"),
        priced("a-mid", "0.2", "0.4"),
        priced("y-out", "0.1", "0.7"),
    ]
    assert {candidates.blended(p) for _, p in candidates.eligible(rows, rules())} == {D("0.25")}
    # Ordered z-out, a-mid, b-mid, y-out: index (4 - 1) // 2 = 1, the lower middle.
    assert candidates.reference(candidates.eligible(rows, rules()))[0]["tag"] == "a-mid"
    # At one blended price a lower output is a higher input: output decides first.
    pair = candidates.eligible([rows[3], rows[0]], rules())
    assert candidates.reference(pair)[0]["tag"] == "z-out"
    odd = [*rows, priced("x-low", "0.1", "0.1")]  # blended 0.1: first of five
    assert candidates.reference(candidates.eligible(odd, rules()))[0]["tag"] == "a-mid"
    assert candidates.reference([]) is None


def test_the_blend_weighs_input_three_to_one():
    cheap_input = priced("cheap-input", "0.1", "1.0")  # blended 0.325
    cheap_output = priced("cheap-output", "0.4", "0.3")  # blended 0.375
    anchor = candidates.reference(candidates.eligible([cheap_output, cheap_input], rules()))
    assert anchor[0]["tag"] == "cheap-input"
    assert candidates.blended({"input": D("0.1"), "output": D("1.0")}) == D("0.325")


def test_the_reference_endpoint_is_always_admitted():
    rows = [priced("a", "1", "2"), priced("b", "1", "3"), priced("c", "2", "1")]
    # Blended 1.25, 1.5, 1.75: the reference is b. Even at a margin of 1 it is admitted.
    price, admitted = candidates.anchored(entry(), rows, rules("1"))
    assert (price["input"], price["output"]) == (D(1), D(3))
    assert admitted == rows[:2]


def test_cache_prices_come_from_the_reference_endpoint_else_the_model_level():
    model = entry(
        pricing={
            "prompt": per_token("1"),
            "completion": per_token("2"),
            "input_cache_read": per_token("0.1"),
            "input_cache_write": per_token("1.25"),
        }
    )
    own = priced("acme", "1", "2")
    own["pricing"]["input_cache_read"] = per_token("0.2")
    price, _ = candidates.anchored(model, [own], rules())
    assert price == {
        "input": D(1),
        "output": D(2),
        "cache_read": D("0.2"),
        "cache_write": D("1.25"),
    }


def test_an_unpooled_model_keeps_its_model_level_price():
    src = sources()
    built = snapshot.build(src["catalogue"], src["endpoints"], rules(), src["read_at"])
    for model in ("cohere/command-a-plus", "~anthropic/claude-opus-latest"):
        assert model not in src["endpoints"]
        assert built["models"][model]["endpoints"] is None
        assert built["models"][model]["pricing"] == snapshot.pricing(
            by_id(src["catalogue"])[model]["pricing"]
        )
    model = entry()
    assert candidates.anchored(model, None, rules()) == (
        candidates.prices_of(model["pricing"]),
        None,
    )
    # A pooled model is published at its reference price, not its model-level one.
    assert by_id(src["catalogue"])[OPUS]["pricing"]["completion"] == "0.00002"
    assert built["models"][OPUS]["pricing"]["output"] == "22"


def test_an_all_fp4_model_has_no_admitted_endpoint():
    src = sources()
    laguna, listed = by_id(src["catalogue"])[ALL_FP4], src["endpoints"][ALL_FP4]
    assert {candidates.quantization(e) for e in listed} == {"fp4"}
    assert candidates.anchored(laguna, listed, rules()) == (
        candidates.prices_of(laguna["pricing"]),
        [],
    )
    _, dropped = candidates.screen(src["catalogue"], src["endpoints"], requirements())
    assert dropped[ALL_FP4] == "no admitted endpoint"
    model = entry()
    quantized = [priced(f"q/{q}", "0.1", "0.2", quantization=q) for q in SUB_8_BIT]
    assert candidates.anchored(model, quantized, rules()) == (
        candidates.prices_of(model["pricing"]),
        [],
    )
