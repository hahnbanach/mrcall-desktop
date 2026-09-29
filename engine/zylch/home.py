"""Where the engine's data lives: ``$ZYLCH_HOME`` or ``~/.zylch``.

Every path that used to be spelled ``~/.zylch/...`` resolves through
:func:`zylch_home`, so a hosted daemon whose ``HOME`` is its own profile
directory (M2 of docs/execution-plans/2026-09-29-toward-sandbox.md) still
finds the profiles root, the company memory directory and the embedding
cache where the host keeps them. Read at import by the modules that keep
module-level constants (``zylch.cli.profiles``), so the variable must be
set before the engine is imported — the systemd unit does that.
"""

import os


def zylch_home() -> str:
    override = os.environ.get("ZYLCH_HOME", "").strip()
    if override:
        return override
    return os.path.expanduser("~/.zylch")
