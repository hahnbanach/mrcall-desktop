"""Real installed kernel CLI -> local WebSocket -> engine dispatch/SQLite.

Run with CS_PROJECT_KERNEL_PYTHON pointing at an isolated installed kernel Python.
Normal engine-only tests skip this cross-repository acceptance test. Authentication
is a fixed fixture, not a claim about Firebase. No real project or account is used.
"""
import asyncio
import json
import os
import subprocess
import threading

import pytest


@pytest.mark.skipif(not os.environ.get("CS_PROJECT_KERNEL_PYTHON"),
                    reason="cross-repository kernel installation not supplied")
def test_installed_kernel_shared_project_journey(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from websockets.sync.server import serve
    from zylch.memory.store import _install_pragmas
    from zylch.rpc import projects
    from zylch.rpc.dispatch import dispatch_raw
    from zylch.services import project_store
    from zylch.storage import database
    from zylch.storage.models import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'company.db'}")
    _install_pragmas(engine)
    Base.metadata.create_all(engine, tables=database.memory_tables())
    project_store.ensure_space(engine)
    monkeypatch.setattr(database, "current_memory_engine", lambda: engine)
    monkeypatch.setattr(projects, "author", lambda: "fixture-owner")
    seen = []

    def handler(ws):
        assert ws.request.headers["Authorization"] == "Bearer fixture-id-token"
        for raw in ws:
            request = json.loads(raw)
            assert request["method"].startswith("projects."), request["method"]
            seen.append(request["method"])
            response = asyncio.run(dispatch_raw(raw, lambda *_: None))
            ws.send(json.dumps(response))

    with serve(handler, "127.0.0.1", 0) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"ws://127.0.0.1:{server.socket.getsockname()[1]}"
        home = tmp_path / "home"
        home.mkdir()
        workspace = tmp_path / "operator's workspace"
        workspace.mkdir()
        (workspace / "manifest.toml").write_text(f'''
[company]
name = "Fixture"
display_name = "Fixture"
from_name = "Fixture Ops"
slug = "fixture"
prog_name = "fixture-cs"
[operator]
email_address = "ops@fixture.example"
[engine]
owner_uid = "fixture-owner"
ws_url = "{url}"
[engine.accounts]
default = "ops@fixture.example"
"ops@fixture.example" = "fixture-owner"
[crm]
adapter = "none"
[producer]
adapter = "none"
''')
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("CS_", "EMAIL_", "ENGINE_", "FIREBASE_", "IMAP_", "SMTP_"))}
        env["HOME"] = str(home)
        python = os.environ["CS_PROJECT_KERNEL_PYTHON"]
        bootstrap = ("from cs import auth; auth.get_id_token=lambda *_: 'fixture-id-token'; "
                     "from cs.cli import main; raise SystemExit(main())")

        def cli(*args, ok=True):
            result = subprocess.run([python, "-c", bootstrap, "project", *map(str, args)],
                                    cwd=workspace, env=env, capture_output=True, text=True,
                                    timeout=30)
            if ok:
                assert result.returncode == 0, (args, result.stdout, result.stderr)
            else:
                assert result.returncode != 0, (args, result.stdout)
            return result

        cli("new", "first-project", "--title", "An authored project")
        assert not (workspace / "docs/projects").exists()
        assert "first-project" in cli("list").stdout
        assert "An authored project" in cli("show", "first-project", "README.md").stdout
        cli("new", "first-project", ok=False)

        first = workspace / "working copy"
        second = workspace / "colleague copy"
        cli("checkout", "first-project", first)
        cli("checkout", "first-project", second)
        original = (first / "status.md").read_bytes()
        edited = original + b"\nVerified next action.\r\n"
        (first / "status.md").write_bytes(edited)
        cli("save", first)  # preview must not mutate
        assert "Verified next action" not in cli("show", "first-project").stdout
        cli("save", first, "--commit")
        assert "Verified next action" in cli("show", "first-project").stdout
        (second / "status.md").write_bytes(original + b"\nA stale conflicting edit.\n")
        cli("save", second, "--commit", ok=False)
        assert (second / "status.md").read_bytes().endswith(b"A stale conflicting edit.\n")
        old = workspace / "original-status.bin"
        cli("show", "first-project", "status.md", "--revision", "1", "--output", old)
        assert old.read_bytes() == original
        cli("history", "first-project", "status.md")

        legacy = workspace / "docs/projects/imported-project"
        legacy.mkdir(parents=True)
        payloads = {"status.md": b"Authored memory\r\nNo final newline",
                    "files/proposal.bin": bytes(range(256)) * 32,
                    "meetings/meeting.md": b"\xef\xbb\xbfMeeting with BOM\r\n"}
        for path, value in payloads.items():
            target = legacy / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value)
        cli("import", legacy)
        assert "imported-project" not in cli("list").stdout
        cli("import", legacy, "--commit")
        cli("import", legacy, "--commit")  # interruption/retry convergence
        exported = workspace / "exported project"
        cli("checkout", "imported-project", exported)
        for path, value in payloads.items():
            assert (legacy / path).read_bytes() == value
            assert (exported / path).read_bytes() == value
        history = project_store.listing(project="imported-project", path="status.md")
        assert history["total"] == 1

        # Switching the engine's company invalidates the old copy, even if names match.
        other = create_engine(f"sqlite:///{tmp_path / 'other-company.db'}")
        _install_pragmas(other)
        Base.metadata.create_all(other, tables=database.memory_tables())
        project_store.ensure_space(other)
        monkeypatch.setattr(database, "current_memory_engine", lambda: other)
        (exported / "status.md").write_bytes(b"Do not redirect this change")
        cli("save", exported, "--commit", ok=False)
        assert project_store.listing()["total"] == 0
        other.dispose()
        server.shutdown()
        thread.join(timeout=5)
    assert {"projects.create", "projects.list", "projects.files", "projects.read",
            "projects.write", "projects.history"}.issubset(seen)
    engine.dispose()
