#!/usr/bin/env python3
"""Migrate a legacy email-keyed desktop profile to a Firebase-UID-keyed one.

Before this rename, profile dirs were named after the user's email
(`~/.zylch/profiles/<email>/`). After the Firebase signin landing in
2026-05, new profiles live at `~/.zylch/profiles/<firebase_uid>/` so an
email change never strands the on-disk data. This one-shot script
upgrades an existing profile to the new layout.

What it does:

  1. Move the directory atomically:
        ~/.zylch/profiles/<email>/  →  ~/.zylch/profiles/<uid>/
  2. Patch the relocated .env to set:
        OWNER_ID=<uid>
        EMAIL_ADDRESS=<email>
     If those keys already exist they are overwritten in place
     (preserving comments and the order of all other keys).

What it does NOT do:

  - Touch SQLite contents. The engine's owner-scoped storage uses
    OWNER_ID from the .env to scope rows, so existing data keyed on
    the old owner_id remains under the old value. If you need rows
    re-keyed (e.g. OAuthToken.owner_id), do a separate UPDATE pass —
    most desktop installs are single-user and won't need it.
  - Push profile state anywhere; everything stays on this machine.
  - Trigger the engine. Run this while no sidecar / CLI is using the
    profile (otherwise the directory rename will race).

Usage:

  python3 migrate_profile_to_uid.py \
      --email user@example.com --uid AbCdEf1234567890XyZ

Add --dry-run to preview, --force to overwrite an existing
~/.zylch/profiles/<uid>/ directory.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger("migrate_profile_to_uid")


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
# Firebase UIDs in practice are 28 alphanumeric characters; keep the
# matcher permissive (anything Firebase or Google ever issues) without
# allowing path separators or whitespace.
UID_RE = re.compile(r"^[A-Za-z0-9_.-]{4,128}$")

# Same set the engine uses in services/settings_io.py:_quote — kept in
# sync so that a profile round-tripped through Settings doesn't churn
# the migrated lines.
_NEEDS_QUOTE = set(" \t\n\r\"'\\#=$`")


def _quote(value: str) -> str:
    """Match the engine's settings_io._quote behaviour (double-quote on
    any special character, plain otherwise)."""
    if value == "":
        return ""
    if any(ch in _NEEDS_QUOTE for ch in value):
        escaped = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\r\n", "\\n")
            .replace("\n", "\\n")
            .replace("\r", "\\n")
        )
        return f'"{escaped}"'
    return value


def _profiles_root() -> Path:
    return Path.home() / ".zylch" / "profiles"


def _read_env_lines(path: Path) -> List[str]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8") as f:
        return f.readlines()


def _patch_env_lines(lines: List[str], updates: List[Tuple[str, str]]) -> List[str]:
    """Rewrite or append KEY=value pairs.

    For each (key, value) in `updates`: if a `KEY=...` line already
    exists (ignoring comments / blanks), replace it in place. Otherwise
    append at the bottom in the order given. Trailing newline always
    enforced.
    """
    pending = {k: v for k, v in updates}
    out: List[str] = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(raw)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in pending:
            out.append(f"{key}={_quote(pending.pop(key))}\n")
        else:
            out.append(raw)
    if out and not out[-1].endswith("\n"):
        out[-1] = out[-1] + "\n"
    if pending:
        if out and out[-1].strip() != "":
            out.append(f"# Added by migrate_profile_to_uid.py\n")
        for key, value in pending.items():
            out.append(f"{key}={_quote(value)}\n")
    return out


def _atomic_write(target: Path, content: str, mode: int = 0o600) -> None:
    """Write `content` to `target` via a temp file in the same directory."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=".env.", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, target)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def migrate(email: str, uid: str, *, dry_run: bool = False, force: bool = False) -> int:
    if not EMAIL_RE.match(email):
        logger.error("invalid email: %r", email)
        return 2
    if not UID_RE.match(uid):
        logger.error(
            "invalid Firebase UID %r — expected 4–128 chars, alphanumeric / _ . - only",
            uid,
        )
        return 2

    root = _profiles_root()
    src = root / email
    dst = root / uid

    if not src.is_dir():
        logger.error("source profile not found: %s", src)
        return 3

    if dst.exists():
        if not force:
            logger.error(
                "destination profile already exists: %s (use --force to overwrite)", dst
            )
            return 4
        if dry_run:
            logger.info("[dry-run] would remove existing destination: %s", dst)
        else:
            logger.warning("removing existing destination at user request: %s", dst)
            shutil.rmtree(dst)

    env_path_after = dst / ".env"

    logger.info(
        "%s migrate %s → %s",
        "[dry-run]" if dry_run else "",
        src,
        dst,
    )

    if dry_run:
        # Show what the patch would change, but don't touch the disk.
        env_path_before = src / ".env"
        original = _read_env_lines(env_path_before)
        patched = _patch_env_lines(
            original, [("OWNER_ID", uid), ("EMAIL_ADDRESS", email)]
        )
        added_or_changed = [
            line for line in patched if line not in original and line.strip()
        ]
        if added_or_changed:
            logger.info(
                "[dry-run] .env changes:\n  %s", "  ".join(added_or_changed)
            )
        else:
            logger.info("[dry-run] .env already has OWNER_ID + EMAIL_ADDRESS set correctly")
        return 0

    # Atomic at the FS level: rename the directory first, then patch
    # .env in the new location.
    os.rename(src, dst)
    logger.info("renamed directory: %s → %s", src, dst)

    if env_path_after.is_file():
        original = _read_env_lines(env_path_after)
        patched = _patch_env_lines(
            original, [("OWNER_ID", uid), ("EMAIL_ADDRESS", email)]
        )
        _atomic_write(env_path_after, "".join(patched), mode=0o600)
        logger.info("patched .env: %s", env_path_after)
    else:
        # No .env? Create a minimal one — the engine needs at least
        # OWNER_ID + EMAIL_ADDRESS to bind storage correctly.
        logger.warning("no .env in moved profile; creating a minimal one")
        content = (
            "# Created by migrate_profile_to_uid.py\n"
            f"OWNER_ID={_quote(uid)}\n"
            f"EMAIL_ADDRESS={_quote(email)}\n"
        )
        _atomic_write(env_path_after, content, mode=0o600)

    logger.info("migration complete")
    return 0


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Rename ~/.zylch/profiles/<email>/ to ~/.zylch/profiles/<uid>/ "
            "and patch its .env with OWNER_ID + EMAIL_ADDRESS."
        ),
    )
    parser.add_argument(
        "--email", required=True, help="Existing profile's email (current dir name)"
    )
    parser.add_argument(
        "--uid", required=True, help="Firebase UID for the migrated profile"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned changes without touching disk",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite ~/.zylch/profiles/<uid>/ if it already exists",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable debug logging"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    return migrate(
        email=args.email,
        uid=args.uid,
        dry_run=args.dry_run,
        force=args.force,
    )


if __name__ == "__main__":
    sys.exit(main())
