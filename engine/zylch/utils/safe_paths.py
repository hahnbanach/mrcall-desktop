"""Path primitives shared by every code path that writes or reads a
model- or sender-supplied filename: attachment saving (`zylch.email`),
document search and download targets (`zylch.tools.paths`).

Kept dependency-free so `zylch.email` can import it without pulling in
the tool layer.
"""

import os
import re
from collections.abc import Iterable

# Split on both separators: `os.path.basename` only knows the host's, and
# an attachment named `..\\..\\x` must not survive on a POSIX host either.
_SEPARATORS = re.compile(r"[\\/]+")


class PathRefused(ValueError):
    """A path resolved outside its allowed root(s)."""


def confine(path: str, roots: Iterable[str]) -> str:
    """Return `realpath(path)` if it lies inside one of `roots`, else raise.

    Resolves the *final* path (symlinks included) before comparing, so a
    link inside a root cannot point out of it. `roots` are resolved the
    same way. The path need not exist.
    """
    real = os.path.realpath(path)
    allowed = []
    for root in roots:
        if not root:
            continue
        real_root = os.path.realpath(root)
        allowed.append(real_root)
        if real == real_root or real.startswith(real_root.rstrip(os.sep) + os.sep):
            return real
    raise PathRefused(f"path is outside the allowed folders: {', '.join(allowed) or '(none)'}")


def safe_attachment_name(raw: str, index: int) -> str:
    """Reduce a sender-supplied filename to a plain basename.

    `sub/dir.pdf` becomes `dir.pdf`; non-ASCII is preserved (the caller
    decodes RFC 2047 first); empty, dot-only or NUL-bearing names become
    `attachment_<index>`.
    """
    name = (raw or "").replace("\0", "")
    name = _SEPARATORS.split(name)[-1].strip()
    if not name or set(name) == {"."}:
        return f"attachment_{index}"
    return name
