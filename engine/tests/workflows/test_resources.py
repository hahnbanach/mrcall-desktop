import hashlib
import json
import re
from importlib.resources import files

import pytest

from zylch.workflows.resources import list_workflows, load_reference, load_workflow
from zylch.workflows.errors import WorkflowError


@pytest.fixture(autouse=True)
def cleanup_test_data():
    yield


def test_complete_preserved_inventory_and_canonical_links():
    root = files("zylch.workflows")
    migration = root.joinpath("migration", "2026-10-12")
    manifest = json.loads(migration.joinpath("manifest.json").read_text())
    assert len(manifest["files"]) == 17
    assert {
        label: sum(entry["input"] == label for entry in manifest["files"])
        for label in ("financial-global", "legal-global", "legal-kernel")
    } == {"financial-global": 2, "legal-global": 8, "legal-kernel": 7}
    for entry in manifest["files"]:
        original = root.joinpath(
            "migration",
            "2026-10-12",
            "originals",
            entry["input"],
            *entry["relative_path"].split("/"),
        )
        data = original.read_bytes()
        assert len(data) == entry["size"]
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
        assert entry["adaptation"]
        if entry["canonical"]:
            canonical = root.joinpath("bundles", *entry["canonical"].split("/"))
            assert hashlib.sha256(canonical.read_bytes()).hexdigest() == entry["canonical_sha256"]
    metadata = list_workflows()
    assert [entry["name"] for entry in metadata] == ["cs-financial-statements", "cs-legal-research"]
    assert len(metadata[0]["references"]) == 1
    assert len(metadata[1]["references"]) == 4
    for entry in metadata:
        assert len(entry["version"]) == 64
        procedure = load_workflow(entry["name"])
        for link in re.findall(r"\]\((references/[^)]+|PROVENANCE.md)\)", procedure):
            assert load_reference(entry["name"], link)
    legal = load_workflow("cs-legal-research")
    assert "The scheduled operator never invokes it" in legal
    assert "company's own affairs" in legal
    assert "expiry_weekdays" in load_reference("cs-legal-research", "references/deadlines.md")


@pytest.mark.parametrize(
    "name,reference",
    [
        ("../secret", "PROVENANCE.md"),
        ("cs-legal-research", "../SKILL.md"),
        ("cs-legal-research", "scripts/count_days.py"),
    ],
)
def test_resource_paths_are_not_caller_controlled(name, reference):
    with pytest.raises(WorkflowError):
        load_reference(name, reference)
