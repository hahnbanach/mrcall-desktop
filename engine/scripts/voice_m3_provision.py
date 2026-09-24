"""Provision the authorized isolated M3 synthetic fixture, never a personal profile.

Requires stopped test service/exclusive lock. No paid call or model request.
Tokens pass through anonymous pipes; only the encrypted Firebase refresh token
is stored. Company capability is persisted exclusively through memory.join.
"""

import argparse
import fcntl
import json
import logging
import os
import sqlite3
import subprocess
import time
import uuid
from pathlib import Path

import httpx
import jwt
from cryptography.fernet import Fernet
from dotenv import dotenv_values, set_key


def previous_caller(profile, values, private_key):
    """Read only the completed authorized M1 carrier call, not a contact store."""
    with sqlite3.connect(f"file:{profile / 'voice-smoke.db'}?mode=ro", uri=True) as db:
        rows = db.execute(
            """SELECT c.carrier_id FROM smoke_carrier c JOIN smoke_calls s
            ON s.session_id=c.session_id WHERE s.state='closed' AND s.reserved_microusd>0"""
        ).fetchall()
    if len(rows) != 1:
        raise ValueError("Expected the single approved M1 call")
    now = int(time.time())
    token = jwt.encode(
        {
            "application_id": values["VONAGE_APPLICATION_ID"],
            "iat": now,
            "exp": now + 120,
            "jti": str(uuid.uuid4()),
        },
        private_key.read_bytes(),
        algorithm="RS256",
    )
    result = httpx.get(
        "https://api-eu.vonage.com/v1/calls/" + rows[0][0],
        headers={"Authorization": "Bearer " + token},
        timeout=15,
    )
    result.raise_for_status()
    data = result.json()
    if data["status"] != "completed":
        raise ValueError("Previous call is not closed")
    number = data["from"]["number"]
    return "+" + number.lstrip("+")


def mint_refresh(args, uid):
    source = """
import json, logging, sys
from types import SimpleNamespace
from dotenv import dotenv_values
from cs import auth
logging.disable(logging.CRITICAL)
try:
    refs = json.load(sys.stdin)
    settings = SimpleNamespace(firebase_sa_path=refs["sa"],
        firebase_web_api_key=dotenv_values(refs["env"])["FIREBASE_WEB_API_KEY"])
    refresh = auth.mint_refresh_token(settings, refs["uid"])
    token = auth._exchange(settings, refresh)["id_token"]
    sys.stdout.write(json.dumps({"refresh":refresh,"id":token}))
except Exception:
    sys.exit(1)
"""
    result = subprocess.run(
        [args.kernel_python, "-c", source],
        input=json.dumps({"sa": args.firebase_sa, "env": args.firebase_env, "uid": uid}),
        capture_output=True,
        text=True,
        timeout=80,
    )
    if result.returncode:
        raise ValueError("Headless credential preparation failed")
    return json.loads(result.stdout)


def provision(args):
    logging.disable(logging.CRITICAL)
    os.umask(0o077)
    profile = args.profile_dir.resolve(strict=True)
    values = dotenv_values(profile / ".env", interpolate=False)
    for name in ("OWNER_ID", "VOICE_SMOKE_TEST_PROFILE"):
        if values.get(name) != profile.name:
            raise ValueError("Isolated profile binding required")
    if (
        (profile / "zylch.db").exists()
        or (profile / "voice-engine.db").exists()
        or values.get("MEMORY_KEY")
    ):
        raise ValueError("Only the unused isolated M1 skeleton can be provisioned")
    fd = os.open(profile / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        caller = previous_caller(profile, values, args.vonage_key)
        tokens = mint_refresh(args, profile.name)
        additions = {
            "VOICE_ENGINE_ISOLATED_PROFILE": profile.name,
            "LLM_DAILY_BUDGET_USD": "3",
            "ENCRYPTION_KEY": Fernet.generate_key().decode(),
            "FIREBASE_WEB_API_KEY": dotenv_values(args.firebase_env)["FIREBASE_WEB_API_KEY"],
            "AUTO_UPDATE_ENABLED": "false",
        }
        for key, value in additions.items():
            set_key(profile / ".env", key, value)
        values.update(additions)
        inherited = {
            k: os.environ[k] for k in ("HOME", "PATH", "LANG", "PYTHONPATH") if k in os.environ
        }
        os.environ.clear()
        os.environ.update(inherited)
        os.environ.update({k: v for k, v in values.items() if v is not None})
        os.environ.update(
            ZYLCH_PROFILE_DIR=str(profile),
            ZYLCH_DB_PATH=str(profile / "voice-engine.db"),
            MEMORY_DB_DIR=str(profile / "memory"),
        )
        from zylch.storage import database as db
        from zylch.storage.models import Base
        from zylch.memory.company_key import mint_key
        from zylch.memory.store import open_memory_engine, prepare_store
        from zylch.memory.join import join
        from zylch.rpc.firebase_auth import verify_firebase_id_token
        from zylch.storage.storage import Storage
        from zylch.utils.encryption import is_encryption_enabled
        from zylch.services.voice.agent_config import get_config, update_config
        from tests.voice.m2_fixture import populate, configuration

        assert verify_firebase_id_token(tokens["id"])["sub"] == profile.name
        Base.metadata.create_all(db.get_engine(), tables=db.profile_tables())
        key = mint_key()
        memory = open_memory_engine(key, create=True)
        prepare_store(memory, key, created_by=profile.name)
        assert join(key)["ok"]
        populate(key, profile.name, known=caller)
        assert is_encryption_enabled()
        Storage.get_instance().store_firebase_refresh_token(profile.name, tokens["refresh"])
        saved = get_config()
        config = configuration() | {
            "called_number": values["VOICE_SMOKE_TEST_NUMBER"],
            "instructions": "Rispondi in italiano. Sei l'assistente del test MrCall. Usa solo i fatti autorizzati della memoria sintetica. Distingui lo storico dalle informazioni nuove del chiamante. Rettifica esplicitamente gli errori già pronunciati.",
            "limits": {"duration_seconds": 120, "max_calls": 2, "budget_microusd": 2000000},
        }
        update_config(profile.name, saved["space_id"], saved["revision"], config)
        db.dispose_engine()
        print(
            json.dumps(
                {
                    "isolated_fixture": "ready",
                    "facts": "M2 synthetic filters and Thursday delivery",
                    "refresh_token": "encrypted",
                    "id_token": "memory only",
                    "ledger": "preserved",
                }
            )
        )
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-dir", type=Path, required=True)
    parser.add_argument("--kernel-python", required=True)
    parser.add_argument("--firebase-sa", required=True)
    parser.add_argument("--firebase-env", required=True)
    parser.add_argument("--vonage-key", type=Path, required=True)
    try:
        provision(parser.parse_args())
    except Exception:
        raise SystemExit("Isolated M3 provisioning failed; no secret details emitted.") from None


if __name__ == "__main__":
    main()
