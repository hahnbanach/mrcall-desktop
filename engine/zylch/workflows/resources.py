import hashlib
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Any

from .errors import WorkflowError

_NAMES = ("cs-financial-statements", "cs-legal-research")


def _bundle(name: str) -> Traversable:
    if name not in _NAMES:
        raise WorkflowError("workflow_not_found")
    return files("zylch.workflows").joinpath("bundles", name)


def _inventory(root: Traversable, prefix: str = "") -> list[tuple[str, bytes]]:
    result = []
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        path = prefix + child.name
        if child.is_dir():
            result.extend(_inventory(child, path + "/"))
        elif child.name != "__pycache__" and not child.name.endswith(".pyc"):
            result.append((path, child.read_bytes()))
    return result


def list_workflows() -> list[dict[str, Any]]:
    result = []
    for name in _NAMES:
        root = _bundle(name)
        inventory = _inventory(root)
        digest = hashlib.sha256()
        for path, data in inventory:
            digest.update(path.encode() + b"\0" + str(len(data)).encode() + b"\0" + data)
        procedure = root.joinpath("SKILL.md").read_text(encoding="utf-8")
        description = next(
            line.removeprefix("description: ")
            for line in procedure.splitlines()
            if line.startswith("description: ")
        )
        result.append(
            {
                "name": name,
                "description": description,
                "version": digest.hexdigest(),
                "references": [path for path, _ in inventory if path.startswith("references/")],
            }
        )
    return result


def load_workflow(name: str) -> str:
    return _bundle(name).joinpath("SKILL.md").read_text(encoding="utf-8")


def load_reference(name: str, reference: str) -> str:
    root = _bundle(name)
    allowed = {
        path
        for path, _ in _inventory(root)
        if path.startswith("references/") or path == "PROVENANCE.md"
    }
    if reference not in allowed:
        raise WorkflowError("workflow_reference_not_found")
    return root.joinpath(*reference.split("/")).read_text(encoding="utf-8")
