"""Where tools may read and write on disk — one policy for every caller.

The tool classes (`read_document_tool`, `download_attachment_tool`,
`run_python_tool`), their solve copies (`services/solve_tools.py`) and the
draft tools' attachment paths all resolve through here, so hosted-engine
confinement is decided once.

Hosted (`runtime.is_serving()`): the downloads folder is
`<profile>/downloads`, scratch is `<profile>/scratch`, the search set is
exactly those two, `DOCUMENT_PATHS` / `DOWNLOADS_DIR` are ignored, and any
path a tool takes must resolve inside the search set. The profile root
(`.env`, `zylch.db`, `whatsapp.db`) is never a write target.

Local (stdio sidecar): today's folders keep working; only the profile-root
refusal and the attachment basename rule apply.
See docs/briefs/2026-09-29-toward-sandbox.md.
"""

import glob
import logging
import os

from zylch import runtime
from zylch.utils.safe_paths import PathRefused, confine

logger = logging.getLogger(__name__)

LOCAL_SCRATCH_DIR = "/tmp/zylch"
LOCAL_ATTACHMENTS_FALLBACK = "/tmp/zylch/attachments"

HOSTED_IGNORED_SETTINGS = {
    "DOCUMENT_PATHS": "ignored on a hosted engine: documents are read from the profile's downloads folder",
    "DOWNLOADS_DIR": "ignored on a hosted engine: attachments are saved in the profile's downloads folder",
}


def profile_dir() -> str:
    return os.environ.get("ZYLCH_PROFILE_DIR", "")


def _hosted_subdir(name: str) -> str:
    base = profile_dir()
    if not base:
        raise PathRefused("no active profile directory")
    path = os.path.join(base, name)
    os.makedirs(path, exist_ok=True)
    return path


def downloads_dir() -> str:
    """Where attachments land by default."""
    if runtime.is_serving():
        return _hosted_subdir("downloads")
    configured = os.environ.get("DOWNLOADS_DIR", "").strip()
    if configured:
        return os.path.expanduser(configured)
    home = os.path.expanduser("~")
    if not os.path.isdir(home):
        return LOCAL_ATTACHMENTS_FALLBACK
    return os.path.join(home, "Downloads")


def scratch_dir() -> str:
    """Working directory for `run_python` output and other tool scratch."""
    if runtime.is_serving():
        return _hosted_subdir("scratch")
    os.makedirs(LOCAL_SCRATCH_DIR, exist_ok=True)
    return LOCAL_SCRATCH_DIR


def search_paths() -> list[str]:
    """Folders `read_document` may search; existing directories only."""
    if runtime.is_serving():
        return [p for p in (downloads_dir(), scratch_dir()) if os.path.isdir(p)]

    home = os.path.expanduser("~")
    downloads = downloads_dir()
    defaults = [
        os.path.join(home, "gdrive-shared"),
        os.path.join(home, "Documents"),
        downloads,
        LOCAL_ATTACHMENTS_FALLBACK,
        LOCAL_SCRATCH_DIR,
    ]
    if profile_dir():
        defaults.append(profile_dir())

    doc_paths = os.environ.get("DOCUMENT_PATHS", "")
    paths: list[str] = []
    if doc_paths:
        configured = [os.path.expanduser(p.strip()) for p in doc_paths.split(",") if p.strip()]
        paths = [p for p in configured if os.path.isdir(p)]
    if not paths:
        paths = [p for p in defaults if os.path.isdir(p)]
    # `~/Downloads` is always searchable: that's where download_attachment writes.
    if os.path.isdir(downloads) and downloads not in paths:
        paths.append(downloads)
    return paths


def find_document(filename: str) -> str | None:
    """Locate `filename` inside the search set, or return None.

    An absolute path is accepted only if it resolves inside the search set;
    otherwise the name is matched as a substring under every search folder.
    There is no cwd-relative fallback. Raises PathRefused for an absolute
    path outside the set.
    """
    paths = search_paths()
    if os.path.isabs(filename):
        real = confine(filename, paths)
        return real if os.path.isfile(real) else None

    for base in paths:
        pattern = os.path.join(base, "**", f"*{filename}*")
        for hit in glob.glob(pattern, recursive=True):
            try:
                real = confine(hit, [base])
            except PathRefused:
                continue
            if os.path.isfile(real):
                return real
    return None


def resolve_download_target(target_dir: str | None) -> str:
    """Directory attachments are written to; created if missing.

    Hosted: `downloads_dir()`, and an explicit `target_dir` must resolve
    inside it. Local: the explicit dir, else `DOWNLOADS_DIR`, else
    `~/Downloads` (today's rules). In both modes the profile root is refused.
    Raises PathRefused.
    """
    if runtime.is_serving():
        root = downloads_dir()
        resolved = confine(os.path.expanduser(target_dir), [root]) if target_dir else root
    else:
        resolved = os.path.expanduser(target_dir) if target_dir else downloads_dir()
        resolved = os.path.realpath(resolved)

    base = profile_dir()
    if base and resolved == os.path.realpath(base):
        raise PathRefused("the profile folder itself is not a download target")

    try:
        os.makedirs(resolved, exist_ok=True)
    except OSError:
        if runtime.is_serving():
            raise
        resolved = LOCAL_ATTACHMENTS_FALLBACK
        os.makedirs(resolved, exist_ok=True)
    return resolved


def confine_attachment_paths(paths: list[str]) -> list[str]:
    """Outgoing-mail attachments: on a hosted engine each must lie inside
    the search set (the model could otherwise attach another file it can
    name). Local engines keep today's behaviour. Raises PathRefused."""
    if not runtime.is_serving():
        return paths
    roots = search_paths()
    return [confine(p, roots) for p in paths]
