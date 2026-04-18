"""Read a file from the user's document folders.

Ported from zylch/services/solve_tools.py::_read_document. Honors the
platform-aware path logic (commit 87e6216) and does NOT truncate extracted
text — the full content is returned to the LLM.
"""

import glob
import logging
import os
from typing import Any, Dict, List

from .base import Tool, ToolResult, ToolStatus

logger = logging.getLogger(__name__)


# Plain-text extensions we can read directly.
TEXT_EXTS = (".txt", ".md", ".csv", ".json", ".xml", ".log", ".yaml", ".yml")


def _collect_search_paths() -> List[str]:
    """Platform-aware document search paths.

    `~/Downloads` is ALWAYS included (implicitly), even when DOCUMENT_PATHS
    is set — that's where `download_attachment` places its output, so
    `read_document` must be able to find those files without extra config.
    """
    home = os.path.expanduser("~")
    profile_dir = os.environ.get("ZYLCH_PROFILE_DIR", "")
    downloads = os.path.join(home, "Downloads")

    defaults = [
        os.path.join(home, "gdrive-shared"),
        os.path.join(home, "Documents"),
        downloads,
        "/tmp/zylch/attachments",
        "/tmp/zylch",
    ]
    if profile_dir:
        defaults.append(profile_dir)

    doc_paths = os.environ.get("DOCUMENT_PATHS", "")
    if doc_paths:
        configured = [os.path.expanduser(p.strip()) for p in doc_paths.split(",") if p.strip()]
        paths = [p for p in configured if os.path.isdir(p)]
        if not paths:
            paths = [p for p in defaults if os.path.isdir(p)]
    else:
        paths = [p for p in defaults if os.path.isdir(p)]

    # Ensure ~/Downloads is always in the search set (idempotent).
    if os.path.isdir(downloads) and downloads not in paths:
        paths.append(downloads)

    return paths


class ReadDocumentTool(Tool):
    """Read a file from the user's document folders."""

    def __init__(self):
        super().__init__(
            name="read_document",
            description=(
                "Read a file from the user's document folders."
                " Searches by filename across all registered paths."
                " Accepts absolute paths too."
            ),
        )

    async def execute(self, filename: str = "", **kwargs) -> ToolResult:
        logger.debug(f"[read_document] execute(args={{'filename_len':" f" {len(filename)}}})")
        if not filename:
            result = ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="No filename provided",
            )
            logger.debug(f"[read_document] -> status={result.status}")
            return result

        # Absolute path shortcut
        path: str = ""
        if os.path.isabs(filename) and os.path.isfile(filename):
            path = filename
        else:
            paths = _collect_search_paths()
            if not paths:
                result = ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error=("No document folders found." " Add DOCUMENT_PATHS to your profile .env"),
                )
                logger.debug(f"[read_document] -> status={result.status}")
                return result

            found: List[str] = []
            for base in paths:
                pattern = os.path.join(base, "**", f"*{filename}*")
                found.extend(glob.glob(pattern, recursive=True))

            # If filename has a path component, try it as a relative path too.
            if not found and os.path.isfile(filename):
                found.append(os.path.abspath(filename))

            if not found:
                result = ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error=(f"No file matching '{filename}' in:" f" {', '.join(paths)}"),
                )
                logger.debug(f"[read_document] -> status={result.status}")
                return result

            path = found[0]

        ext = os.path.splitext(path)[1].lower()

        if ext == ".pdf":
            result = ToolResult(
                status=ToolStatus.SUCCESS,
                data={"text": "", "path": path, "format": "pdf"},
                message=(f"Found PDF: {path}\n" f"Use run_python to read it with pypdf."),
            )
            logger.debug(f"[read_document] -> status={result.status} format=pdf")
            return result

        if ext in TEXT_EXTS:
            try:
                with open(path, "r", errors="replace") as f:
                    content = f.read()
                result = ToolResult(
                    status=ToolStatus.SUCCESS,
                    data={
                        "text": content,
                        "path": path,
                        "format": ext.lstrip(".") or "text",
                    },
                    message=f"File: {path}",
                )
                logger.debug(f"[read_document] -> status={result.status}" f" bytes={len(content)}")
                return result
            except Exception as e:
                logger.error(f"[read_document] read failed: {e}")
                result = ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error=f"Could not read {path}: {e}",
                )
                logger.debug(f"[read_document] -> status={result.status}")
                return result

        result = ToolResult(
            status=ToolStatus.SUCCESS,
            data={
                "text": "",
                "path": path,
                "format": ext.lstrip(".") or "binary",
            },
            message=(f"Found: {path} ({ext})\n" f"Use run_python to process this file."),
        )
        logger.debug(f"[read_document] -> status={result.status} format={ext}")
        return result

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": ("Filename or partial name to search"),
                    },
                },
                "required": ["filename"],
            },
        }
