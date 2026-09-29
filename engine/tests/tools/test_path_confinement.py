"""Hosted-engine path confinement (brief 2026-09-29-toward-sandbox, M1).

Criterion 1 (first two clauses) and 3: with the serve flag set, no tool may
read a sibling profile's `.env` — not by absolute path, not through a
customer-set `DOCUMENT_PATHS` — and `run_python` is refused. Without the
flag the local engine keeps its folders.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from zylch import runtime
from zylch.services import solve_tools
from zylch.tools import paths
from zylch.tools.gmail_tools import _normalize_attachment_paths
from zylch.tools.python_exec import HOSTED_REFUSAL, run_python_code
from zylch.tools.read_document_tool import ReadDocumentTool
from zylch.tools.run_python_tool import RunPythonTool
from zylch.utils.safe_paths import PathRefused, confine, safe_attachment_name


@pytest.fixture
def host(tmp_path, monkeypatch):
    """Two profiles on one host, A active; returns (profile_a, profile_b)."""
    profiles = tmp_path / "profiles"
    a = profiles / "uidA"
    b = profiles / "uidB"
    for prof in (a, b):
        prof.mkdir(parents=True)
        (prof / ".env").write_text(f"EMAIL_PASSWORD=secret-of-{prof.name}\n")
        (prof / "zylch.db").write_bytes(b"db")
    (a / "downloads").mkdir()
    (a / "downloads" / "invoice.txt").write_text("invoice A")
    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(a))
    monkeypatch.delenv("DOCUMENT_PATHS", raising=False)
    monkeypatch.delenv("DOWNLOADS_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return a, b


@pytest.fixture
def serving(monkeypatch):
    monkeypatch.setattr(runtime, "_serving", True)
    yield
    monkeypatch.setattr(runtime, "_serving", False)


# ─── primitives ──────────────────────────────────────────


def test_confine_accepts_inside_and_refuses_outside(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    assert confine(str(root / "x" / "y.txt"), [str(root)]).startswith(str(root.resolve()))
    with pytest.raises(PathRefused):
        confine(str(tmp_path / "elsewhere.txt"), [str(root)])
    with pytest.raises(PathRefused):
        confine(str(root / ".." / "elsewhere.txt"), [str(root)])
    # A sibling whose name merely starts with the root's name is outside.
    with pytest.raises(PathRefused):
        confine(str(tmp_path / "rootx" / "f"), [str(root)])


def test_confine_follows_symlinks_out_of_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "secret").write_text("s")
    os.symlink(tmp_path / "secret", root / "link")
    with pytest.raises(PathRefused):
        confine(str(root / "link"), [str(root)])


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("/etc/passwd", "passwd"),
        ("../../x", "x"),
        ("sub/dir.pdf", "dir.pdf"),
        ("..\\..\\win.txt", "win.txt"),
        ("fattura né.pdf", "fattura né.pdf"),
        ("", "attachment_3"),
        ("..", "attachment_3"),
        ("a\0b", "ab"),
    ],
)
def test_safe_attachment_name(raw, expected):
    assert safe_attachment_name(raw, 3) == expected


# ─── read_document, hosted ───────────────────────────────


def _read(filename: str):
    return asyncio.run(ReadDocumentTool().execute(filename=filename))


def test_hosted_absolute_path_to_sibling_env_is_refused(host, serving):
    _a, b = host
    result = _read(str(b / ".env"))
    assert result.status.value == "error"
    assert "secret-of-uidB" not in (result.message or "") + (result.error or "")
    assert solve_tools._read_document({"filename": str(b / ".env")}).startswith("Read refused")


def test_hosted_own_env_is_not_in_the_search_set(host, serving):
    a, _b = host
    assert _read(str(a / ".env")).status.value == "error"
    assert _read(".env").status.value == "error"


def test_hosted_document_paths_setting_is_ignored(host, serving, monkeypatch):
    a, b = host
    monkeypatch.setenv("DOCUMENT_PATHS", str(b.parent))
    assert paths.search_paths() == [str(a / "downloads"), str(a / "scratch")]
    result = _read("*.env")
    assert result.status.value == "error"
    assert "secret-of" not in (result.error or "")


def test_hosted_reads_its_own_download(host, serving):
    result = _read("invoice")
    assert result.status.value == "success"
    assert "invoice A" in result.data["text"]
    assert solve_tools._read_document({"filename": "invoice"}).startswith("File:")


def test_hosted_no_cwd_relative_fallback(host, serving, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "stray.txt").write_text("stray")
    assert _read("stray.txt").status.value == "error"


# ─── read_document, local ────────────────────────────────


def test_local_documents_and_document_paths_still_resolve(host, tmp_path, monkeypatch):
    docs = tmp_path / "home" / "Documents"
    docs.mkdir(parents=True)
    (docs / "contract.txt").write_text("local contract")
    assert str(docs) in paths.search_paths()
    assert "local contract" in _read("contract").data["text"]

    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "note.md").write_text("extra note")
    monkeypatch.setenv("DOCUMENT_PATHS", str(extra))
    assert "extra note" in _read("note").data["text"]


def test_local_absolute_path_outside_folders_is_refused(host, tmp_path):
    (tmp_path / "outside.txt").write_text("x")
    assert _read(str(tmp_path / "outside.txt")).status.value == "error"


# ─── download target ─────────────────────────────────────


def test_hosted_target_dir_must_be_inside_downloads(host, serving):
    a, b = host
    assert paths.resolve_download_target(None) == str(a / "downloads")
    assert paths.resolve_download_target(str(a / "downloads" / "sub")) == str(a / "downloads" / "sub")
    for bad in (str(a), str(b), str(b / "downloads"), "/tmp", "~"):
        with pytest.raises(PathRefused):
            paths.resolve_download_target(bad)


def test_local_profile_root_is_never_a_target(host):
    a, _b = host
    with pytest.raises(PathRefused):
        paths.resolve_download_target(str(a))
    assert paths.resolve_download_target(str(a / "downloads")) == str(a / "downloads")


# ─── outgoing attachments ────────────────────────────────


def test_hosted_outgoing_attachment_outside_search_set_is_refused(host, serving):
    a, b = host
    with pytest.raises(PathRefused):
        _normalize_attachment_paths([str(b / ".env")])
    assert _normalize_attachment_paths([str(a / "downloads" / "invoice.txt")]) == [
        str(a / "downloads" / "invoice.txt")
    ]


def test_local_outgoing_attachment_paths_unchanged(host, tmp_path):
    p = tmp_path / "anywhere.pdf"
    assert _normalize_attachment_paths([str(p)]) == [str(p)]


# ─── run_python ──────────────────────────────────────────


def test_hosted_run_python_is_refused(host, serving):
    run = run_python_code("print(1)")
    assert run.error == HOSTED_REFUSAL
    result = asyncio.run(RunPythonTool().execute(code="print(1)", description="x"))
    assert result.status.value == "error" and HOSTED_REFUSAL in result.error
    assert solve_tools._run_python({"code": "print(1)"}) == HOSTED_REFUSAL


def test_local_run_python_runs_in_scratch(host):
    run = run_python_code("import os; print(os.getcwd())")
    assert run.ok and run.stdout.strip() == os.path.realpath(paths.LOCAL_SCRATCH_DIR)


def test_hosted_glob_dotdot_traversal_is_refused(host, serving):
    """`glob` resolves literal `..` components, so a name like
    `sub/../../../uidB/.env` really reaches B's file; confine() must drop it."""
    a, b = host
    (a / "downloads" / "sub").mkdir()
    result = _read("sub/../../../uidB/.env")
    assert result.status.value == "error"
    assert "secret-of-uidB" not in (result.error or "") + (result.message or "")
    assert (b / ".env").read_text().startswith("EMAIL_PASSWORD")
