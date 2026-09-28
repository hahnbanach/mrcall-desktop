"""M2 source acceptance: real Firebase + cs CLI against disposable SQLite only.

Run from engine with PYTHONPATH=. and explicit credential references. No normal
profile activation, service changes, paid calls, personal memory or token files.
Uses the same frozen synthetic history as the M2 tests. All output is sanitized.
"""

import argparse
import asyncio
import json
import logging
import subprocess
import tempfile
from pathlib import Path

import pytest

from tests.voice.m2_fixture import seed
from tests.voice.m2_journey import journey
from zylch.auth import clear_session
from zylch.rpc.firebase_auth import verify_firebase_id_token
from zylch.storage import database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel-python", required=True)
    parser.add_argument("--firebase-sa", required=True)
    parser.add_argument("--firebase-env", required=True)
    parser.add_argument("--owner-uid", required=True)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    try:
        # Reuse the installed kernel's headless auth without get_id_token's
        # disk cache. Tokens travel only through an anonymous subprocess pipe.
        source = """
import json, logging, sys
from types import SimpleNamespace
from dotenv import dotenv_values
from cs import auth
logging.disable(logging.CRITICAL)
try:
    refs = json.load(sys.stdin)
    settings = SimpleNamespace(
        firebase_sa_path=refs["firebase_sa"],
        firebase_web_api_key=dotenv_values(refs["firebase_env"])["FIREBASE_WEB_API_KEY"],
    )
    refresh = auth.mint_refresh_token(settings, refs["owner_uid"])
    sys.stdout.write(auth._exchange(settings, refresh)["id_token"])
except Exception:
    sys.exit(1)
"""
        minted = subprocess.run(
            [args.kernel_python, "-c", source],
            input=json.dumps(vars(args)),
            capture_output=True,
            text=True,
            timeout=80,
        )
        if minted.returncode != 0:
            raise RuntimeError("Headless authentication failed")
        token = minted.stdout
        assert verify_firebase_id_token(token)["sub"] == args.owner_uid
        with (
            tempfile.TemporaryDirectory(prefix="mrcall-voice-m2-") as path,
            pytest.MonkeyPatch.context() as patch,
        ):
            root = Path(path)
            seed(root, patch, owner=args.owner_uid)
            try:
                report = asyncio.run(journey(root, args.kernel_python, token))
                report["authentication"] = "real Firebase RS256; token held in memory only"
                print(json.dumps(report, indent=2))
            finally:
                clear_session()
                database.dispose_engine()
        return 0
    except Exception:
        print("M2 demonstration failed; no credential details emitted.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
