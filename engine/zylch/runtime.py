"""Process-wide runtime mode.

`zylch serve` marks the process as *serving* before it activates the
profile. Tools consult `is_serving()` to apply hosted-engine policy (path
confinement, refused code execution). The flag is a module variable, never
an environment variable: the profile `.env` is loaded with `override=True`
after this is set, and `settings.update` writes `.env`, so an environment
flag could be flipped by a customer. See
docs/briefs/2026-09-29-toward-sandbox.md.
"""

_serving = False


def mark_serving() -> None:
    """Called once by `zylch serve`; irreversible for the process lifetime."""
    global _serving
    _serving = True


def is_serving() -> bool:
    return _serving
