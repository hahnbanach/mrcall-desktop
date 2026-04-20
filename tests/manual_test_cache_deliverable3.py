"""Manual test for Deliverable 3 — chat_compaction.compact_if_needed.

Two scenarios:
  A) 50-turn synthetic history (~60K tokens) → compaction runs, first turn
     and last 10 turns are intact, middle is replaced by a summary block.
  B) 5-turn history (below threshold) → returned unchanged (identity).

SMTP is blocked even though the compaction path never sends email — belt
and suspenders.
"""

import asyncio
import logging
import os
import sys

os.environ["ZYLCH_PROFILE"] = "user@example.com"

from dotenv import load_dotenv  # noqa: E402

profile_env = os.path.expanduser(
    "~/.zylch/profiles/user@example.com/.env",
)
load_dotenv(profile_env, override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("anthropic").setLevel(logging.WARNING)

import smtplib  # noqa: E402


class _BlockedSMTP:
    def __init__(self, *a, **kw):
        raise RuntimeError("SMTP is blocked during tests")


smtplib.SMTP = _BlockedSMTP  # type: ignore
smtplib.SMTP_SSL = _BlockedSMTP  # type: ignore


def _pad_text(i: int) -> str:
    """Produce ~5k chars of meaningful-ish prose for turn i."""
    blob = (
        f"Turn {i}. We were discussing the 2026 product roadmap for the "
        "Cafezal cold-brew private label. Pricing tiers across volumes "
        "250ml, 500ml, 750ml have been debated. The supplier offered a "
        "minimum order of 10,000 bottles at €1.80/unit ex-works for the "
        "500ml SKU. Shipping to Milano adds €0.12/unit. Payment terms "
        "are 60 days net with a 2% early-payment discount at 15 days. "
        "We need to align final terms before the November sales kickoff. "
    )
    # Repeat to hit ~5000 chars.
    out = blob
    while len(out) < 5000:
        out += blob
    return out[:5000]


async def scenario_a() -> bool:
    from zylch.services.chat_compaction import (
        compact_if_needed,
        _estimate_tokens,
    )

    # Build 50 turns of alternating user/assistant, ~5k chars each.
    history = []
    for i in range(1, 51):
        role = "user" if i % 2 == 1 else "assistant"
        history.append({"role": role, "content": f"[msg {i}] " + _pad_text(i)})

    estimated = _estimate_tokens(history)
    print(f"[A] synthetic 50-turn history: {len(history)} msgs, ~{estimated} tokens")
    if estimated < 80_000:
        # Shouldn't happen — our synthetic turns are ~1250 tokens each, so
        # 50 turns ~= 62.5K. But guard against drift.
        print(f"[A] WARN: estimated={estimated} below soft_limit 80k, bumping content")
        for h in history:
            h["content"] = h["content"] * 2
        estimated = _estimate_tokens(history)
        print(f"[A] re-estimated: {estimated} tokens")

    first_turn = history[0]
    last_10 = history[-10:]

    result = await compact_if_needed(history)
    print(f"[A] compacted history length: {len(result)} (input: {len(history)})")

    if len(result) >= len(history):
        print("[A] FAIL: compacted history is not shorter")
        return False
    if result[0] != first_turn:
        print("[A] FAIL: first turn changed")
        return False
    if result[-10:] != last_10:
        print("[A] FAIL: last 10 turns changed")
        return False
    middle = result[1:-10]
    if len(middle) != 1:
        print(f"[A] FAIL: expected exactly 1 summary block, got {len(middle)}")
        return False
    summary_msg = middle[0]
    content = summary_msg.get("content", "")
    if not isinstance(content, str):
        print(f"[A] FAIL: summary content is not a string: {type(content)}")
        return False
    if "[Previous conversation summary" not in content:
        print("[A] FAIL: summary block missing marker")
        return False
    print(f"[A] summary chars: {len(content)}")
    print(f"[A] summary preview: {content[:200]}...")
    print("[A] PASS")
    return True


async def scenario_b() -> bool:
    from zylch.services.chat_compaction import compact_if_needed

    history = [
        {"role": "user", "content": "ciao"},
        {"role": "assistant", "content": "Ciao!"},
        {"role": "user", "content": "come stai?"},
        {"role": "assistant", "content": "Bene grazie, e tu?"},
        {"role": "user", "content": "ok."},
    ]
    result = await compact_if_needed(history)
    if result is not history:
        # Content may be the same object; we also accept deep equality
        if result != history:
            print("[B] FAIL: short history was modified")
            return False
    print("[B] PASS — short history returned unchanged")
    return True


async def main() -> int:
    a = await scenario_a()
    b = await scenario_b()
    print()
    print("=" * 60)
    print(f"Scenario A (compaction triggered): {'PASS' if a else 'FAIL'}")
    print(f"Scenario B (short history):        {'PASS' if b else 'FAIL'}")
    print("=" * 60)
    return 0 if (a and b) else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
