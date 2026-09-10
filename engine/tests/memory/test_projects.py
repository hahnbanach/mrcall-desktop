"""Written company documents exercise real SQLite, company joins and RPC."""

import asyncio
import base64
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import inspect, select

from tests.memory.test_split_store import _boot
from zylch.memory.company_key import current_company_key
from zylch.memory.join import join, merge_store_into
from zylch.services import project_store as p
from zylch.storage import database as dbm


def encoded(raw=b"first\r\n\x00\xff"):
    return base64.b64encode(raw).decode("ascii")


@pytest.fixture
def boot(tmp_path, monkeypatch, embedder):
    import zylch.memory as memory_pkg
    import zylch.memory.embeddings as emb_mod

    monkeypatch.setattr(memory_pkg, "EmbeddingEngine", lambda *a, **k: embedder)
    monkeypatch.setattr(emb_mod, "EmbeddingEngine", lambda *a, **k: embedder)

    def start(name, **kwargs):
        return _boot(monkeypatch, tmp_path, name, **kwargs)

    yield start
    dbm.dispose_engine()


def test_bytes_revisions_binding_pagination(boot):
    owner = boot("a", key=None, source=None)
    space = p.listing()["space_id"]
    first = p.write(space, "demo", "attachment.bin", encoded(), 0, owner)
    assert p.read("demo", "attachment.bin")["content_base64"] == encoded()
    assert p.write(space, "demo", "attachment.bin", encoded(), 0, owner) == first
    second = p.write(space, "demo", "attachment.bin", encoded(b"second"), 1, "colleague")
    assert second["revision"] == 2 and second["author_uid"] == "colleague"
    assert p.read("demo", "attachment.bin", 1)["content_base64"] == encoded()
    assert p.listing(project="demo", path="attachment.bin", limit=1)["total"] == 2
    assert (
        p.listing(project="demo", path="attachment.bin", limit=1, offset=1)["items"][0]["revision"]
        == 1
    )
    assert "project_documents" not in inspect(dbm.get_engine()).get_table_names()
    with dbm.get_session() as session:
        assert session.execute(select(p.D)).first() is not None


def test_concurrent_compare_and_swap(boot):
    owner = boot("a", key=None, source=None)
    space = p.listing()["space_id"]
    p.write(space, "demo", "status.md", encoded(b"original"), 0, owner)

    def save(i):
        try:
            return p.write(space, "demo", "status.md", encoded(str(i).encode()), 1, owner)[
                "revision"
            ]
        except p.ProjectError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(save, (1, 2))) == [-32040, 2]
    assert p.listing(project="demo", path="status.md")["total"] == 2


def test_isolation_same_company_rebind_stale_space_and_unavailable(boot):
    owner = boot("a", key=None, source=None)
    company = current_company_key()
    space = p.listing()["space_id"]
    p.write(space, "demo", "status.md", encoded(), 0, owner)
    boot("colleague", key=company, source="provisioned")
    assert p.read("demo", "status.md")["space_id"] == space
    boot("b", key=None, source=None)
    assert p.listing()["items"] == []
    with pytest.raises(p.ProjectError) as exc:
        p.write(space, "demo", "status.md", encoded(), 0, "b")
    assert exc.value.code == -32041
    dbm.set_memory_engine(None, "unavailable")
    with pytest.raises(p.ProjectError) as exc:
        p.listing()
    assert exc.value.code == -32043


@pytest.mark.parametrize(
    "path", ["../x", "/x", "a//b", "a/./b", "C:/x", "a\\b", "a\x00b", "x" * 513]
)
def test_invalid_paths_do_not_write(boot, path):
    boot("a", key=None, source=None)
    with pytest.raises(p.ProjectError) as exc:
        p.write(p.listing()["space_id"], "demo", path, encoded(), 0, "a")
    assert exc.value.code == -32602
    assert p.listing()["items"] == []


def test_scaffold_atomic_validation_and_conflict(boot):
    boot("a", key=None, source=None)
    space = p.listing()["space_id"]
    with pytest.raises(p.ProjectError):
        p.create(space, "demo", {"good": encoded(), "bad": "!bad!"}, "a")
    assert p.listing()["items"] == []
    out = p.create(space, "demo", {"status.md": encoded(), "notes.md": encoded(b"notes")}, "a")
    assert len(out["files"]) == 2
    with pytest.raises(p.ProjectError) as exc:
        p.create(space, "demo", {"extra": encoded()}, "a")
    assert exc.value.code == -32040
    assert p.listing(project="demo")["total"] == 2


def test_join_preserves_history_and_changes_space(boot):
    boot("destination", key=None, source=None)
    dst_key = current_company_key()
    dst_space = p.listing()["space_id"]
    boot("source", key=None, source=None)
    src_space = p.listing()["space_id"]
    p.write(src_space, "demo", "status.md", encoded(), 0, "source")
    p.write(src_space, "demo", "status.md", encoded(b"new"), 1, "source")
    assert join(dst_key)["ok"]
    assert p.listing()["space_id"] == dst_space
    assert p.read("demo", "status.md", 1)["content_base64"] == encoded()
    with pytest.raises(p.ProjectError) as exc:
        p.write(src_space, "demo", "status.md", encoded(b"later"), 2, "source")
    assert exc.value.code == -32041


def test_divergent_join_refuses_before_membership_or_any_copy(boot):
    boot("destination", key=None, source=None)
    dst_key = current_company_key()
    dst = dbm.current_memory_engine()
    p.write(p.listing()["space_id"], "demo", "status.md", encoded(b"dst"), 0, "dst")
    boot("source", key=None, source=None)
    src_key = current_company_key()
    src_space = p.listing()["space_id"]
    p.write(src_space, "other", "safe.md", encoded(), 0, "src")
    p.write(src_space, "demo", "status.md", encoded(b"src"), 0, "src")
    with pytest.raises(p.ProjectError) as exc:
        join(dst_key)
    assert exc.value.code == -32040
    assert current_company_key() == src_key
    assert p.listing()["space_id"] == src_space
    with dst.connect() as conn:
        assert len(conn.execute(select(p.D)).all()) == 1


def test_join_prefix_and_identical_head_divergent_history(boot):
    boot("destination", key=None, source=None)
    dst_key = current_company_key()
    dst = dbm.current_memory_engine()
    boot("source", key=None, source=None)
    src_key = current_company_key()
    src = dbm.current_memory_engine()
    space = p.listing()["space_id"]
    p.write(space, "demo", "status.md", encoded(b"first"), 0, "src")
    merge_store_into(src, dst, src_key, dst_key)
    p.write(space, "demo", "status.md", encoded(b"second"), 1, "src")
    assert merge_store_into(src, dst, src_key, dst_key)["project_revisions"] == 1
    assert merge_store_into(src, dst, src_key, dst_key)["project_revisions"] == 0
    with dst.begin() as conn:
        conn.execute(p.R.update().where(p.R.c.revision == 1).values(author_uid="different"))
    with pytest.raises(p.ProjectError):
        merge_store_into(src, dst, src_key, dst_key)


def test_real_dispatch_errors_and_payload_redaction(boot, monkeypatch, caplog):
    from zylch.rpc import projects
    from zylch.rpc.dispatch import dispatch_raw

    boot("a", key=None, source=None)
    monkeypatch.setattr(projects, "author", lambda: "test-owner")

    def call(method, params):
        return asyncio.run(
            dispatch_raw(
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}),
                lambda *args: None,
            )
        )

    caplog.set_level("DEBUG")
    payload = encoded(b"PRIVATE-PROJECT-CONTENT")
    result = call(
        "projects.write",
        {
            "space_id": p.listing()["space_id"],
            "project": "demo",
            "path": "status.md",
            "content_base64": payload,
            "expected_revision": 0,
        },
    )
    assert result["result"]["revision"] == 1
    assert payload not in caplog.text and "PRIVATE-PROJECT-CONTENT" not in caplog.text
    assert call("projects.files", {"project": "missing"})["error"]["code"] == -32044
    assert call("projects.list", {"limit": True})["error"]["code"] == -32602
    assert call("projects.write", {})["error"]["code"] == -32602
    monkeypatch.setattr(p, "listing", lambda **kwargs: (_ for _ in ()).throw(RuntimeError(payload)))
    assert payload not in str(call("projects.list", {}))
    assert payload not in caplog.text


@pytest.mark.parametrize(
    "field,value",
    [
        ("project", "bad_slug"),
        ("project", "trailing-"),
        ("project", None),
        ("expected_revision", True),
        ("expected_revision", -1),
        ("content_base64", "ü"),
        ("content_base64", "bad!"),
        ("content_base64", encoded(b"x" * (p.MAX_BYTES + 1))),
        ("space_id", None),
    ],
)
def test_malformed_and_oversize_inputs(boot, field, value):
    boot("a", key=None, source=None)
    params = {
        "space_id": p.listing()["space_id"],
        "project": "demo",
        "path": "status.md",
        "content_base64": encoded(),
        "expected_revision": 0,
        "author": "a",
    }
    params[field] = value
    with pytest.raises(p.ProjectError) as exc:
        p.write(**params)
    assert exc.value.code == -32602
    assert p.listing()["items"] == []


def test_scaffold_aggregate_limit_and_metadata_queries_exclude_bytes(boot):
    from sqlalchemy import event

    boot("a", key=None, source=None)
    space = p.listing()["space_id"]
    with pytest.raises(p.ProjectError):
        p.create(space, "demo", {"a": encoded(b"x" * (1024 * 1024)), "b": encoded()}, "a")
    assert p.listing()["items"] == []
    p.write(space, "demo", "file.bin", encoded(b"x" * p.MAX_BYTES), 0, "a")
    statements = []
    engine = dbm.current_memory_engine()

    def trace(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", trace)
    try:
        p.listing(project="demo")
        p.listing(project="demo", path="file.bin")
    finally:
        event.remove(engine, "before_cursor_execute", trace)
    assert not any("project_revisions.content" in query for query in statements)


def test_old_source_without_project_tables_and_unknown_capability(boot):
    from sqlalchemy import create_engine

    from zylch.services.project_join import merge_projects

    boot("a", key=None, source=None)
    dst = dbm.current_memory_engine()
    old = create_engine("sqlite://")
    with old.begin() as source, dst.begin() as destination:
        assert merge_projects(source, destination) == {
            "project_documents": 0,
            "project_revisions": 0,
        }
    old.dispose()
    from zylch.memory.company_key import mint_key

    boot("unknown", key=mint_key(), source="typed")
    with pytest.raises(p.ProjectError) as exc:
        p.listing()
    assert exc.value.code == -32043


def test_join_sql_failure_never_leaks_document_bytes(boot, monkeypatch, caplog):
    from sqlalchemy.exc import StatementError

    from zylch.rpc.dispatch import dispatch_raw
    from zylch.services import project_join

    boot("destination", key=None, source=None)
    destination_key = current_company_key()
    boot("source", key=None, source=None)
    source_key = current_company_key()
    secret = b"PRIVATE-REVISION-SQL-PARAMETERS"

    def fail(*args):
        raise StatementError(
            "query failed",
            "INSERT INTO project_revisions",
            {"content": secret},
            RuntimeError("oops"),
        )

    monkeypatch.setattr(project_join, "merge_projects", fail)
    caplog.set_level("DEBUG")
    result = asyncio.run(
        dispatch_raw(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "memory.join",
                    "params": {"key": destination_key},
                }
            ),
            lambda *args: None,
        )
    )
    assert result["error"]["code"] == -32603
    assert secret.decode() not in str(result)
    assert secret.decode() not in caplog.text
    assert current_company_key() == source_key


def test_join_partial_schema_refuses_instead_of_losing_documents(boot):
    from sqlalchemy import create_engine

    from zylch.services.project_join import merge_projects

    boot("destination", key=None, source=None)
    broken = create_engine("sqlite://")
    p.D.create(broken)
    with (
        broken.begin() as source,
        dbm.current_memory_engine().begin() as destination,
        pytest.raises(p.ProjectError) as exc,
    ):
        merge_projects(source, destination)
    assert exc.value.code == -32040
    broken.dispose()
