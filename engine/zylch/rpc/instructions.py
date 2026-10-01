"""Standing operator instructions: the one write door and the read-only preview."""

from collections.abc import Callable
from typing import Any

from zylch.services import operator_instructions as instructions


def author() -> str:
    from zylch.cli.utils import get_owner_id

    return get_owner_id()


async def instructions_store(params: dict[str, Any], notify: Callable[..., None]) -> dict[str, Any]:
    """instructions.store(space_id, path, content_base64, expected_revision) -> document metadata."""
    return instructions.store(**params, author=author())


async def instructions_preview(
    params: dict[str, Any], notify: Callable[..., None]
) -> dict[str, Any]:
    """instructions.preview() -> {space_id, documents: [{path, revision, sha256, content_base64}], block}."""
    return instructions.preview()


METHODS = {
    "instructions.store": instructions_store,
    "instructions.preview": instructions_preview,
}
