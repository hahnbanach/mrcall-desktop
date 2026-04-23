"""Manual test for Deliverable 1 — history prompt caching.

Test shape:
  - Turn 1: fresh cache_control breakpoints; Anthropic should WRITE the
    cached prefix (cache_creation_input_tokens > 0, cache_read ~ 0).
  - Turns 2 & 3: same prefix; Anthropic should READ from cache
    (cache_read_input_tokens > 0).

To keep the cache cold for turn 1 we include a random nonce that changes
with every test run, so we don't pick up stale cache entries written by
earlier runs of this same test.

Run with the cafe124 profile:
    venv/bin/python tests/manual_test_cache_deliverable1.py
"""

import asyncio
import logging
import os
import sys
import uuid

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

# Monkey-patch SMTP so no email can escape even by accident.
import smtplib  # noqa: E402


class _BlockedSMTP:
    def __init__(self, *a, **kw):
        raise RuntimeError("SMTP is blocked during tests")


smtplib.SMTP = _BlockedSMTP  # type: ignore
smtplib.SMTP_SSL = _BlockedSMTP  # type: ignore


async def main() -> int:
    from zylch.config import settings
    from zylch.assistant.core import ZylchAIAgent

    if not settings.anthropic_api_key:
        print("FAIL: no ANTHROPIC_API_KEY in profile .env", file=sys.stderr)
        return 1

    agent = ZylchAIAgent(
        api_key=settings.anthropic_api_key,
        tools=[],
        provider="anthropic",
        max_tokens=256,
    )

    # Unique per-run nonce to keep turn 1 cold — baked into the first
    # user turn so the cache prefix is unique for this test run.
    run_tag = uuid.uuid4().hex[:12]
    history_template = [
        {
            "role": "user",
            "content": (
                f"[test_run={run_tag}] ciao, come stai? " "Ti faccio una chiacchierata lunga."
            ),
        },
        {"role": "assistant", "content": "Ciao! Sto bene, grazie. E tu?"},
        {"role": "user", "content": "Bene, grazie. Che ore sono?"},
        {
            "role": "assistant",
            "content": "Non ho accesso all'orario di sistema, dimmi pure tu.",
        },
        {"role": "user", "content": "Ok, sono le 15. Dimmi qualcosa di te."},
    ]

    usages = []
    for turn in range(1, 4):
        agent.set_history(list(history_template))
        resp = await agent.process_message(
            user_message=f"dimmi ancora di più (turn {turn}).",
            context={},
        )
        u = dict(agent.last_usage)
        usages.append(u)
        print(
            f"Turn {turn}: input={u.get('input_tokens', 0)} "
            f"output={u.get('output_tokens', 0)} "
            f"cache_read={u.get('cache_read_input_tokens', 0)} "
            f"cache_create={u.get('cache_creation_input_tokens', 0)} "
            f"response_len={len(resp)}"
        )

    print()
    turn1, turn2, turn3 = usages
    print("=" * 60)
    print("VERDICT")
    print("=" * 60)
    t1_create = turn1["cache_creation_input_tokens"]
    t1_read = turn1["cache_read_input_tokens"]
    t2_read = turn2["cache_read_input_tokens"]
    t3_read = turn3["cache_read_input_tokens"]

    ok_turn1_wrote = t1_create > 0 and t1_read == 0
    ok_turn2_read = t2_read > 0
    ok_turn3_read = t3_read > 0

    print(f"Turn 1 wrote cache (create>0, read=0): {ok_turn1_wrote} (create={t1_create}, read={t1_read})")
    print(f"Turn 2 read cache (read>0):            {ok_turn2_read} (read={t2_read})")
    print(f"Turn 3 read cache (read>0):            {ok_turn3_read} (read={t3_read})")

    if ok_turn1_wrote and ok_turn2_read and ok_turn3_read:
        print("\nPASS: Deliverable 1")
        return 0
    print("\nFAIL: Deliverable 1")
    return 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
