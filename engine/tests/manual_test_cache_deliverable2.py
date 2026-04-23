"""Manual test for Deliverable 2 — USER_NOTES injection into chat system.

Flow:
  1. Back up current USER_NOTES in the profile .env.
  2. Write a verifiable directive to USER_NOTES.
  3. Spin up the chat agent and ask a question whose answer ONLY the
     directive can supply.
  4. Assert the agent's reply contains the expected token.
  5. Restore the original USER_NOTES.

SMTP is blocked — no email can escape during the test.
"""

import asyncio
import logging
import os
import sys

os.environ["ZYLCH_PROFILE"] = "mario.alemi@cafe124.it"

from dotenv import load_dotenv  # noqa: E402

profile_env = os.path.expanduser(
    "~/.zylch/profiles/mario.alemi@cafe124.it/.env",
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


async def main() -> int:
    from zylch.cli.profiles import activate_profile
    from zylch.services.settings_io import read_env, update_env

    # Activate profile so settings_io can write its .env.
    activate_profile("mario.alemi@cafe124.it")

    # Back up existing USER_NOTES
    env_before = read_env()
    original_notes = env_before.get("USER_NOTES", "")
    print(f"Backed up USER_NOTES (len={len(original_notes)})")

    # Write verifiable directive
    directive = "FATTO SPECIFICO: il mio compleanno cade l'11 ottobre, non il 4 ottobre."
    update_env({"USER_NOTES": directive})
    # Also set it in os.environ so the process reads the new value.
    os.environ["USER_NOTES"] = directive

    try:
        from zylch.config import settings
        from zylch.assistant.core import ZylchAIAgent

        if not settings.anthropic_api_key:
            print("FAIL: no ANTHROPIC_API_KEY", file=sys.stderr)
            return 1

        agent = ZylchAIAgent(
            api_key=settings.anthropic_api_key,
            tools=[],
            provider="anthropic",
            max_tokens=256,
        )
        agent.clear_history()

        resp = await agent.process_message(
            user_message="When is my birthday?",
            context={},
        )
        print("\nAgent response:")
        print("-" * 60)
        print(resp)
        print("-" * 60)

        # Accept either "October 11", "11 October", "11 ottobre", or "11/10" variants.
        lower = resp.lower()
        ok = (
            "october 11" in lower
            or "11 october" in lower
            or "11 ottobre" in lower
            or "ottobre 11" in lower
            or "11/10" in lower
            or "11-10" in lower
        )
        if ok:
            print("\nPASS: Deliverable 2 — agent used USER_NOTES")
            return 0
        print("\nFAIL: Deliverable 2 — agent did not cite October 11")
        return 2

    finally:
        # Restore original USER_NOTES (empty if there was none)
        update_env({"USER_NOTES": original_notes})
        os.environ["USER_NOTES"] = original_notes
        print(f"\nRestored USER_NOTES (len={len(original_notes)})")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
