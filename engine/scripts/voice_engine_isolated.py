"""Explicit-path M3 daemon; no normal profile activation or automatic channels.

Requires an already provisioned synthetic voice fixture in this private test
profile. Uses the original M1 ledger and its original policy, without a reset.
"""

import argparse
import asyncio
import fcntl
import os
import signal
from pathlib import Path

from dotenv import dotenv_values


def configure(profile):
    profile = profile.resolve(strict=True)
    values = dotenv_values(profile / ".env", interpolate=False)
    if values.get("VOICE_ENGINE_ISOLATED_PROFILE") != profile.name:
        raise ValueError("Isolated engine marker required")
    if (profile / "zylch.db").exists():
        raise ValueError("Populated profile refused")
    if not (profile / "voice-engine.db").is_file():
        raise ValueError("Provision the isolated fixture first")
    for name in ("VOICE_SMOKE_TEST_PROFILE", "OWNER_ID"):
        if values.get(name) != profile.name:
            raise ValueError("Profile binding mismatch")
    # Imports that initialize Settings/storage must follow explicit path binding.
    inherited = {
        k: os.environ[k] for k in ("HOME", "PATH", "LANG", "PYTHONPATH") if k in os.environ
    }
    os.environ.clear()
    os.environ.update(inherited)
    os.environ.update({k: v for k, v in values.items() if v is not None})
    os.environ["ZYLCH_PROFILE_DIR"] = str(profile)
    os.environ["ZYLCH_DB_PATH"] = str(profile / "voice-engine.db")
    os.environ["MEMORY_DB_DIR"] = str(profile / "memory")
    return profile


async def serve(profile, port, rpc_port):
    from zylch.rpc.server_ws import serve_ws
    from zylch.services.voice.listener import voice_listener
    from zylch.services.voice.smoke_config import load_smoke_config
    from zylch.storage.database import attach_memory_store, dispose_engine

    config = load_smoke_config(profile)
    if await asyncio.to_thread(attach_memory_store) is None:
        raise ValueError("Isolated company memory unavailable")
    task = asyncio.create_task(
        serve_ws(
            host="127.0.0.1",
            port=rpc_port,
            warmup=False,
            background=False,
            voice_listener=voice_listener(config, port),
        )
    )
    loop = asyncio.get_running_loop()
    stopping = False

    def stop():
        nonlocal stopping
        if not stopping:
            stopping = True
            task.cancel()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop)
    try:
        await task
    except asyncio.CancelledError:
        pass
    finally:
        # LLM thread completion/settlement is drained by asyncio.run's executor
        # shutdown; do not close its storage here while a request may be running.
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(sig)
    return dispose_engine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--rpc-port", type=int, default=8788)
    args = parser.parse_args()
    profile = args.profile_dir.resolve(strict=True)
    fd = os.open(profile / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        configure(profile)
        dispose = asyncio.run(serve(profile, args.port, args.rpc_port))
        dispose()
    finally:
        os.close(fd)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Isolated voice engine unavailable; inspect sanitized state.") from None
