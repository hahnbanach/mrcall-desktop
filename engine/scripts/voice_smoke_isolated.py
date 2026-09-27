"""Linux test-host bootstrap for an explicit, separately stored M1 profile.

Run with the worktree engine on PYTHONPATH. Never selects or activates a normal
engine profile; the lock covers recovery, serving and provider cleanup.
"""

import argparse
import fcntl
import os
import sys
from pathlib import Path

from zylch.services.voice.live_sip_smoke import run_smoke_server
from zylch.services.voice.smoke_config import load_smoke_config


def run(profile: Path, port: int) -> None:
    profile = profile.resolve(strict=True)
    if not 1 <= port <= 65535:
        raise ValueError("invalid port")
    # An explicit opt-in marker is still required in the private profile file.
    # Refuse a populated engine profile, even if it was accidentally marked.
    if (profile / "zylch.db").exists():
        raise ValueError("populated engine profile is not an isolated M1 profile")
    config = load_smoke_config(profile)
    fd = os.open(profile / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run_smoke_server(config, port)
    finally:
        # Closing releases the lock, including on failure. Never unlink the
        # inode: queued contenders must keep locking the same file.
        os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-dir", required=True, type=Path)
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    try:
        run(args.profile_dir, args.port)
        return 0
    except Exception:
        print("Isolated voice smoke refused or stopped; inspect the safe ledger.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
