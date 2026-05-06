"""PyInstaller runtime hook — runs before any user code in the bundle.

Two responsibilities, both about libmagic on packaged builds:

1. **Point python-magic at the bundled magic database.** libmagic
   compiles the path to ``magic.mgc`` (the compiled magic database it
   uses to identify files) at *its* build time. When we bundle a
   Homebrew-built libmagic into a DMG, that path is
   ``/opt/homebrew/share/misc/magic.mgc`` — which will not exist on
   an end-user Mac that doesn't have Homebrew. Set the ``MAGIC``
   environment variable to point at the copy we shipped inside the
   bundle so libmagic stops trying the build-time path.

2. **Help ctypes find libmagic next to the binary.** PyInstaller's
   ``sys._MEIPASS`` directory IS on the dlopen / dyld search path on
   macOS and Linux, so this is mostly belt-and-suspenders.

Skipped silently when not running from a PyInstaller bundle (dev mode).
"""

from __future__ import annotations

import os
import sys


def _patch_magic_env() -> None:
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return  # not a PyInstaller bundle — dev mode

    candidate_mgc = os.path.join(meipass, "share", "misc", "magic.mgc")
    if os.path.exists(candidate_mgc) and not os.environ.get("MAGIC"):
        # libmagic reads $MAGIC and skips its compiled-in default path.
        os.environ["MAGIC"] = candidate_mgc


_patch_magic_env()
