"""Read / atomically rewrite the active profile's `.env`.

Used by the `settings.*` JSON-RPC methods. Preserves comments and the
ordering of pre-existing keys; new keys are appended at the bottom.
Values are quoted with `shlex.quote` only when they contain characters
that would otherwise change the parse (whitespace, `#`, quote chars,
backslash, `=`). Bare alphanumerics + a few safe symbols stay
unquoted, matching the style produced by `zylch init`.
"""

from __future__ import annotations

import logging
import os
import shlex
from typing import Dict, List, Tuple

from zylch.cli.profiles import get_active_profile, get_active_profile_dir

logger = logging.getLogger(__name__)

# Characters that force quoting. We keep the set tight so most plain
# values (tokens, hosts, emails) stay unquoted and diffs read cleanly.
_NEEDS_QUOTE = set(" \t\n\r\"'\\#=$`")


def _env_path() -> str:
    """Return the absolute path of the active profile's `.env`.

    Raises RuntimeError if no profile is active — this can only happen
    when called outside a `zylch -p ...` CLI context, which means the
    caller is buggy.
    """
    profile_dir = get_active_profile_dir()
    if not profile_dir:
        raise RuntimeError("No active profile — cannot resolve .env path")
    return os.path.join(profile_dir, ".env")


def _quote(value: str) -> str:
    """Quote `value` for safe inclusion as `KEY=value` in a dotenv file."""
    if value == "":
        return ""
    if any(ch in _NEEDS_QUOTE for ch in value):
        return shlex.quote(value)
    return value


def _parse_kv(line: str) -> Tuple[str, str] | None:
    """Return (key, raw_value) from `KEY=value`, ignoring comments / blanks.

    raw_value keeps any surrounding quoting as written on disk; we only
    need the key to know whether to overwrite an existing line.
    """
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    if "=" not in s:
        return None
    key, _, value = s.partition("=")
    key = key.strip()
    if not key:
        return None
    return key, value.strip()


def read_env() -> Dict[str, str]:
    """Return the active profile's `.env` as a `{KEY: value}` dict.

    Quotes are stripped from values so callers get the logical value.
    Missing file -> empty dict.
    """
    path = _env_path()
    out: Dict[str, str] = {}
    if not os.path.isfile(path):
        return out
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            kv = _parse_kv(line)
            if kv is None:
                continue
            key, raw = kv
            # Strip surrounding single or double quotes if present.
            if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
                raw = raw[1:-1]
            out[key] = raw
    return out


def update_env(updates: Dict[str, str]) -> List[str]:
    """Apply `updates` to the active profile's `.env` atomically.

    For each key in `updates`:
      - If a `KEY=...` line already exists, replace that line in place.
      - Otherwise, append `KEY=value` at the bottom (in dict iteration
        order, which in Python 3.7+ preserves caller intent).

    Returns the list of keys that were written. NEVER logs values.
    """
    if not updates:
        return []

    path = _env_path()
    profile = get_active_profile() or "?"
    logger.debug(f"[settings_io] update_env profile={profile} keys={sorted(updates.keys())}")

    # Read existing lines (preserve comments and order).
    existing: List[str] = []
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            existing = f.readlines()

    # Track which updates we've already consumed so we know what to
    # append at the end.
    pending = dict(updates)
    new_lines: List[str] = []
    for line in existing:
        kv = _parse_kv(line)
        if kv is None:
            new_lines.append(line)
            continue
        key, _raw = kv
        if key in pending:
            value = pending.pop(key)
            # Preserve the file's trailing newline convention.
            new_lines.append(f"{key}={_quote(value)}\n")
        else:
            new_lines.append(line)

    if pending:
        # Make sure the previous content ends in a newline before we
        # append a new section.
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines.append("\n")
        if new_lines:
            new_lines.append("\n")
            new_lines.append("# Added by Settings tab\n")
        for key, value in pending.items():
            new_lines.append(f"{key}={_quote(value)}\n")

    # Atomic write: tmp file in same directory, then os.replace.
    tmp_path = path + ".tmp"
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        # Best-effort cleanup of the partial tmp file.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    applied = list(updates.keys())
    logger.info(f"[settings_io] updated profile={profile} keys={sorted(applied)}")
    return applied
