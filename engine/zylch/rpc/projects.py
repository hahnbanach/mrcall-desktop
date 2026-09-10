"""Company project documents: deterministic authenticated RPC, with safe errors."""

from collections.abc import Callable
from typing import Any

from zylch.services import project_store as store


def author() -> str:
    from zylch.cli.utils import get_owner_id

    return get_owner_id()


async def projects_list(params: dict[str, Any], notify: Callable[..., None]) -> dict[str, Any]:
    """projects.list(limit?, offset?) -> paginated project metadata."""
    return store.listing(**params)


async def projects_files(params: dict[str, Any], notify: Callable[..., None]) -> dict[str, Any]:
    """projects.files(project, limit?, offset?) -> paginated document metadata."""
    store.validate_project(params["project"])
    return store.listing(**params)


async def projects_read(params: dict[str, Any], notify: Callable[..., None]) -> dict[str, Any]:
    """projects.read(project, path, revision?) -> document metadata and base64 bytes."""
    return store.read(**params)


async def projects_write(params: dict[str, Any], notify: Callable[..., None]) -> dict[str, Any]:
    """projects.write(space_id, project, path, content_base64, expected_revision) -> document metadata."""
    return store.write(**params, author=author())


async def projects_history(params: dict[str, Any], notify: Callable[..., None]) -> dict[str, Any]:
    """projects.history(project, path, limit?, offset?) -> paginated revision metadata."""
    store.validate_project(params["project"])
    store.validate_path(params["path"])
    return store.listing(**params)


async def projects_create(params: dict[str, Any], notify: Callable[..., None]) -> dict[str, Any]:
    """projects.create(space_id, project, files) -> project metadata and initial files."""
    return store.create(**params, author=author())


METHODS = {
    "projects.list": projects_list,
    "projects.files": projects_files,
    "projects.read": projects_read,
    "projects.write": projects_write,
    "projects.history": projects_history,
    "projects.create": projects_create,
}
