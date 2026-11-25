"""Free snapshot refresh, using real helpers and isolated local Git repositories."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
from unittest.mock import Mock

import pytest

from .resolver_fixture import ENGINE, raw

sys.path.insert(0, str(ENGINE / "scripts"))
import model_table_refresh as script


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def commit(root):
    git(root, "add", "--", "v1")
    git(root, "commit", "-qm", "Synthetic test data")


@pytest.fixture
def rig(tmp_path, monkeypatch):
    source, data, remote = (tmp_path / name for name in ("source", "data", "remote.git"))
    for root in (source, data):
        root.mkdir()
        git(root, "init", "-q", "-b", "model-table")
        git(root, "config", "user.email", "fixture@example.invalid")
        git(root, "config", "user.name", "Fixture")
    git(tmp_path, "init", "-q", "--bare", str(remote))
    source.joinpath("v1").mkdir()
    source.joinpath("v1", "source.txt").write_text("synthetic source\n")
    req_path = source / script.REQUIREMENTS
    req_path.parent.mkdir(parents=True)
    req_path.write_bytes(script.rm.REQUIREMENTS.read_bytes())
    req = json.loads(req_path.read_bytes())
    git(source, "add", "--", script.REQUIREMENTS.as_posix())
    commit(source)
    folder = data / "v1"
    folder.mkdir()
    contract = script.rm.ROLES / "contract"
    for name in ("snapshot.json", "table.json"):
        (folder / name).write_bytes((contract / name.replace(".json", ".example.json")).read_bytes())
    table = json.loads((folder / "table.json").read_bytes())
    for preset in table["presets"].values():
        for role in req["roles"]:
            preset["roles"].setdefault(role, preset["roles"]["CHAT"])
    (folder / "table.json").write_text(json.dumps(script.rm.gates.stamped(table)))
    for name in ("ledger.json", "results.json", "measured.json", "other.txt"):
        (folder / name).write_text("unchanged test bytes\n")
    commit(data)
    git(data, "remote", "add", "origin", str(remote))
    git(data, "push", "-q", "-u", "origin", "model-table")
    monkeypatch.setattr(script, "SOURCE", source)
    monkeypatch.setenv(script.rm.KEY_ENV, "synthetic-private-key")
    monkeypatch.setenv(script.rm.API_ENV, "https://catalogue.invalid/api/v1")
    seen = []
    payloads = raw()
    endpoints = json.loads(payloads["endpoints"])["data"]

    def urlopen(request, timeout):
        assert request.get_method() == "GET"
        url = request.full_url
        seen.append((url, request.get_header("Authorization")))
        if url.endswith("/models"):
            assert request.get_header("Authorization") is None
            return io.BytesIO(payloads["catalogue"])
        if url.endswith("/benchmarks"):
            assert request.get_header("Authorization") == "Bearer synthetic-private-key"
            return io.BytesIO(payloads["benchmarks"])
        assert request.get_header("Authorization") is None
        assert url.endswith("/endpoints")
        model = url.removeprefix("https://catalogue.invalid/api/v1/models/").removesuffix("/endpoints")
        return io.BytesIO(json.dumps({"data": endpoints[model]}).encode())

    monkeypatch.setattr(script.rm.urllib.request, "urlopen", urlopen)
    for name in ("pool", "rankings", "bootstrap", "document"):
        monkeypatch.setattr(script.rm.resolver, name, Mock(side_effect=AssertionError(f"paid/ranking path: {name}")))
    preview = tmp_path / "preview"
    args = ["--data-checkout", str(data), "--preview", str(preview)]
    return data, source, req_path, preview, seen, args


def approve(preview):
    return ["--execute", "--approved-receipt-sha256", script.sha((preview / "receipt.json").read_bytes())]


def test_preview_then_explicit_execution_use_only_catalogue_gets_and_existing_writer(rig, monkeypatch):
    data, source, req_path, preview, seen, args = rig
    writer = script.DataBranch.push
    calls = []

    def push(branch, files, message):
        calls.append(files)
        return writer(branch, files, message)

    monkeypatch.setattr(script.DataBranch, "push", push)
    branch = script.DataBranch(data)
    before, head = script.manifest(branch), git(data, "rev-parse", "HEAD")
    assert script.main(args) == 0
    receipt = json.loads((preview / "receipt.json").read_bytes())
    snap = json.loads((preview / "snapshot.json").read_bytes())
    assert not calls and len(seen) == 220
    assert script.manifest(branch) == before and git(data, "rev-parse", "HEAD") == head
    assert receipt["data_head"] == head and receipt["source_head"] == git(source, "rev-parse", "HEAD")
    assert req_path.read_bytes() == script.rm.REQUIREMENTS.read_bytes()
    assert receipt["requirements_sha256"] == script.sha(script.rm.REQUIREMENTS.read_bytes())
    assert receipt["read_at"] == snap["read_at"] != "2026-10-02T13:36:42Z"
    assert receipt["raw_sha256"]["catalogue"] == hashlib.sha256(raw()["catalogue"]).hexdigest()
    assert receipt["changed_paths"] == ["v1/snapshot.json"]
    assert (preview.stat().st_mode & 0o777) == 0o700
    assert all((p.stat().st_mode & 0o777) == 0o600 for p in preview.iterdir())
    monkeypatch.setattr(script.rm, "read_live", Mock(side_effect=AssertionError("execute must use reviewed bytes")))
    assert script.main(args + approve(preview)) == 0
    assert len(calls) == 1 and set(calls[0]) == {"snapshot.json"}
    assert (data / "v1" / "snapshot.json").read_bytes() == (preview / "snapshot.json").read_bytes()
    assert script.manifest(branch) == {**before, "v1/snapshot.json": receipt["snapshot_sha256"]}
    assert git(data, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD") == "v1/snapshot.json"
    assert git(data, "status", "--porcelain") == ""
    assert script.main(args + approve(preview)) == 1
    assert len(calls) == 1


@pytest.mark.parametrize("damage", ["staged", "untracked", "branch", "ahead", "remote"])
def test_preview_refuses_unclean_or_wrong_data_before_any_provider_call(rig, damage):
    data, source, req_path, preview, seen, args = rig
    if damage == "staged":
        (data / "v1" / "other.txt").write_text("another session\n")
        git(data, "add", "--", "v1/other.txt")
    elif damage == "untracked":
        (data / "private.txt").write_text("another session\n")
    elif damage == "branch":
        git(data, "checkout", "-qb", "wrong-branch")
    elif damage == "ahead":
        (data / "v1" / "other.txt").write_text("ahead\n")
        commit(data)
    else:
        git(data, "update-ref", "refs/remotes/origin/model-table", git(data, "hash-object", "v1/other.txt"))
    assert script.main(args) == 1 and not seen and not preview.exists()


@pytest.mark.parametrize("damage", ["candidate", "raw", "receipt", "data", "source", "requirements"])
def test_execution_refuses_review_drift_without_writing(rig, damage, monkeypatch):
    data, source, req_path, preview, seen, args = rig
    assert script.main(args) == 0
    approved = approve(preview)
    if damage in ("candidate", "raw", "receipt"):
        filename = {"candidate": "snapshot.json", "raw": "endpoints.json", "receipt": "receipt.json"}[damage]
        with (preview / filename).open("ab") as handle:
            handle.write(b" ")
    elif damage == "data":
        (data / "v1" / "other.txt").write_text("new base\n")
        commit(data)
        git(data, "push", "-q", "origin", "model-table")
    elif damage == "source":
        (source / "v1" / "source.txt").write_text("new source\n")
        commit(source)
    else:
        req_path.write_text(req_path.read_text() + " ")
    head = git(data, "rev-parse", "HEAD")
    monkeypatch.setattr(script.DataBranch, "push", Mock(side_effect=AssertionError("must not publish")))
    assert script.main(args + approved) == 1
    assert git(data, "rev-parse", "HEAD") == head and len(seen) == 220


def test_unchanged_table_failure_and_policy_change_never_publish(rig):
    data, source, req_path, preview, seen, args = rig
    req = json.loads(req_path.read_bytes())
    req["presets"]["balanced"]["ceiling"] = 1
    req_path.write_text(json.dumps(req))
    git(source, "add", "--", script.REQUIREMENTS.as_posix())
    commit(source)
    assert script.main(args) == 1 and not preview.exists()
    req["presets"]["balanced"]["ceiling"] = 20
    req["margin"] = 1.5
    req_path.write_text(json.dumps(req))
    git(source, "add", "--", script.REQUIREMENTS.as_posix())
    commit(source)
    assert script.main(args) == 1 and not preview.exists()
    assert git(data, "status", "--porcelain") == ""


@pytest.mark.parametrize("execute", [False, True])
def test_public_requirements_override_is_rejected_before_reads_or_writes(rig, execute, tmp_path, monkeypatch):
    data, source, req_path, preview, seen, args = rig
    if execute:
        assert script.main(args) == 0
        args += approve(preview)
    seen.clear()
    external = tmp_path / "alternate-requirements.json"
    req = json.loads(req_path.read_bytes())
    req["common"]["min_context"] = 210000
    external.write_text(json.dumps(req))
    assert git(source, "status", "--porcelain") == ""
    before = script.manifest(script.DataBranch(data))
    monkeypatch.setattr(script.DataBranch, "push", Mock(side_effect=AssertionError("must not publish")))
    with pytest.raises(SystemExit) as error:
        script.main(args + ["--requirements", str(external)])
    assert error.value.code == 2 and not seen
    assert script.manifest(script.DataBranch(data)) == before


@pytest.mark.parametrize("execute", [False, True])
def test_canonical_requirements_must_match_head_even_if_git_hides_drift(rig, execute, monkeypatch, capsys):
    data, source, req_path, preview, seen, args = rig
    if execute:
        assert script.main(args) == 0
        args += approve(preview)
    seen.clear()
    git(source, "update-index", "--assume-unchanged", "--", script.REQUIREMENTS.as_posix())
    req = json.loads(req_path.read_bytes())
    req["common"]["min_context"] = 210000
    req_path.write_text(json.dumps(req))
    assert git(source, "status", "--porcelain") == ""
    before = script.manifest(script.DataBranch(data))
    monkeypatch.setattr(script.DataBranch, "push", Mock(side_effect=AssertionError("must not publish")))
    assert script.main(args) == 1 and not seen
    assert "canonical requirements differ from source HEAD" in capsys.readouterr().err
    assert script.manifest(script.DataBranch(data)) == before


def test_change_during_live_read_refuses_preview(rig, monkeypatch):
    data, source, req_path, preview, seen, args = rig
    read = script.rm.read_live

    def changed(req):
        result = read(req)
        (data / "v1" / "ledger.json").write_text("another writer\n")
        return result

    monkeypatch.setattr(script.rm, "read_live", changed)
    assert script.main(args) == 1 and not preview.exists()


def test_held_lock_and_dirty_source_refuse_before_provider_read(rig):
    data, source, req_path, preview, seen, args = rig
    with script.DataBranch(data).lock():
        assert script.main(args) == 1
    (source / "v1" / "source.txt").write_text("unreviewed source\n")
    assert script.main(args) == 1 and not seen and not preview.exists()


def test_failed_push_is_not_retried_and_requires_reconciliation(rig, monkeypatch, capsys):
    data, source, req_path, preview, seen, args = rig
    assert script.main(args) == 0
    push = Mock(side_effect=RuntimeError("synthetic ambiguous push"))
    monkeypatch.setattr(script.DataBranch, "push", push)
    assert script.main(args + approve(preview)) == 1
    assert push.call_count == 1
    assert "reconcile actual remote state before retrying" in capsys.readouterr().err


def test_execute_flags_and_standard_library_help(rig):
    data, source, req_path, preview, seen, args = rig
    with pytest.raises(SystemExit) as error:
        script.main(args + ["--execute"])
    assert error.value.code == 2
    done = subprocess.run([sys.executable, "-S", str(ENGINE / "scripts" / "model_table_refresh.py"), "--help"],
                          capture_output=True, text=True, check=False)
    assert done.returncode == 0 and "--approved-receipt-sha256" in done.stdout
    assert not seen
