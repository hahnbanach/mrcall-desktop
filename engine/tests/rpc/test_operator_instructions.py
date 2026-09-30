"""Standing operator instructions: one write door, provenance-based authorisation,
exact preview, and the prompt block built only from stored documents."""

import asyncio
import base64
import hashlib
import json

import pytest

from zylch.services import operator_instructions as oi
from zylch.services import project_store


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


@pytest.fixture
def space(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from zylch.memory.store import _install_pragmas
    from zylch.storage import database
    from zylch.storage.models import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'company.db'}")
    _install_pragmas(engine)
    Base.metadata.create_all(engine, tables=database.memory_tables())
    project_store.ensure_space(engine)
    monkeypatch.setattr(database, "current_memory_engine", lambda: engine)
    monkeypatch.setenv("EMAIL_ADDRESS", "Support@Example.test")
    monkeypatch.setenv("MEMORY_KEY_SOURCE", "mint")
    with project_store.connection() as (_conn, space_id):
        return space_id


def test_paths_accept_only_the_three_shapes():
    assert oi.validate_instruction_path("procedures.md") == "procedures.md"
    assert oi.validate_instruction_path("phone.md") == "phone.md"
    assert oi.validate_instruction_path("mail/a.b@example.test.md") == "mail/a.b@example.test.md"
    for bad in ("notes.md", "mail/../x.md", "mail/no-at.md", "MAIL/a@b.io.md", 3):
        with pytest.raises(project_store.ProjectError) as e:
            oi.validate_instruction_path(bad)
        assert e.value.code == -32602


def test_minter_stores_any_document_and_projects_write_refuses_the_slug(space):
    meta = oi.store(space, "procedures.md", b64("Answer sample requests with the tasting offer."), 0, "a")
    assert meta["revision"] == 1
    oi.store(space, "mail/other@example.test.md", b64("Signs as Other."), 0, "a")
    oi.store(space, "phone.md", b64("We sell coffee."), 0, "a")
    with pytest.raises(project_store.ProjectError) as e:
        from zylch.rpc import projects

        asyncio.run(
            projects.projects_write(
                {
                    "space_id": space,
                    "project": oi.PROJECT,
                    "path": "procedures.md",
                    "content_base64": b64("x"),
                    "expected_revision": 1,
                },
                lambda *_: None,
            )
        )
    assert e.value.code == -32046
    with pytest.raises(project_store.ProjectError) as e:
        asyncio.run(
            projects.projects_create(
                {"space_id": space, "project": oi.PROJECT, "files": {"a.md": b64("x")}},
                lambda *_: None,
            )
        )
    assert e.value.code == -32046


def test_non_minter_stores_only_its_own_mailbox(space, monkeypatch):
    monkeypatch.setenv("MEMORY_KEY_SOURCE", "provision")
    monkeypatch.setenv("EMAIL_ADDRESS", "staff@example.test")
    oi.store(space, "mail/staff@example.test.md", b64("Signs as Staff."), 0, "s")
    for path in ("procedures.md", "phone.md", "mail/support@example.test.md"):
        with pytest.raises(project_store.ProjectError) as e:
            oi.store(space, path, b64("x"), 0, "s")
        assert e.value.code == -32045
    assert project_store.read(oi.PROJECT, "mail/staff@example.test.md")["revision"] == 1


def test_block_and_preview_are_exact(space, monkeypatch):
    assert oi.block() == ""
    assert oi.preview()["documents"] == [] and oi.preview()["block"] == ""
    oi.store(space, "procedures.md", b64("Procedures."), 0, "a")
    assert oi.block() == oi.FRAMING + "Procedures."
    oi.store(space, "mail/support@example.test.md", b64("Identity."), 0, "a")
    assert oi.block() == oi.FRAMING + "Identity." + oi.SEPARATOR + "Procedures."
    view = oi.preview()
    assert view["space_id"] == space
    assert [d["path"] for d in view["documents"]] == [
        "mail/support@example.test.md",
        "procedures.md",
    ]
    for doc in view["documents"]:
        raw = base64.b64decode(doc["content_base64"])
        assert doc["sha256"] == hashlib.sha256(raw).hexdigest()
        assert doc["revision"] == 1
    assert view["block"] == oi.block()
    # Another mailbox of the same company: procedures only, never this identity.
    monkeypatch.setenv("EMAIL_ADDRESS", "staff@example.test")
    assert oi.block() == oi.FRAMING + "Procedures."


def test_personal_section_uses_only_stored_documents(space, monkeypatch):
    from zylch.services.solve_constants import get_personal_data_section

    monkeypatch.setenv("USER_NOTES", "legacy text that must be ignored")
    monkeypatch.delenv("USER_FULL_NAME", raising=False)
    monkeypatch.delenv("USER_SECRET_INSTRUCTIONS", raising=False)
    before = get_personal_data_section()
    assert "legacy text" not in before
    assert "STANDING INSTRUCTIONS" not in before
    oi.store(space, "procedures.md", b64("Never promise same-day delivery."), 0, "a")
    after = get_personal_data_section()
    assert after.startswith("\n" + oi.FRAMING + "Never promise same-day delivery.")
    assert "legacy text" not in after


def test_no_company_memory_means_no_block(monkeypatch):
    from zylch.storage import database

    monkeypatch.setattr(database, "current_memory_engine", lambda: None)
    monkeypatch.setenv("EMAIL_ADDRESS", "support@example.test")
    assert oi.block() == ""


def test_rpc_registration_redaction_and_error_mapping(space):
    from zylch.rpc import dispatch
    from zylch.rpc.methods import METHODS

    assert "instructions.store" in METHODS and "instructions.preview" in METHODS
    redacted = dispatch._redact_params(
        "instructions.store", {"space_id": space, "path": "procedures.md", "content_base64": "QQ=="}
    )
    assert redacted["content_base64"] == "<redacted project document>"
    raw = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "instructions.store",
            "params": {
                "space_id": space,
                "path": "notes.md",
                "content_base64": "QQ==",
                "expected_revision": 0,
            },
        }
    )
    response = asyncio.run(dispatch.dispatch_raw(raw, lambda *_: None))
    assert response["error"]["code"] == -32602
    assert "notes.md" not in response["error"]["message"]
