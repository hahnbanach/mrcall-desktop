"""The host-side join: `zylch -p <profile> memory-status` / `memory-join`.

Drives the click commands with CliRunner on two throwaway profiles; the
join goes through the same join.py the RPC uses.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from zylch.memory.company_key import current_company_key
from zylch.storage import database as dbm

from tests.memory.test_split_store import _boot  # noqa: E402


@pytest.fixture
def stub_embedder(monkeypatch, embedder):
    import zylch.memory as memory_pkg
    import zylch.memory.embeddings as emb_mod

    monkeypatch.setattr(memory_pkg, "EmbeddingEngine", lambda *a, **k: embedder)
    monkeypatch.setattr(emb_mod, "EmbeddingEngine", lambda *a, **k: embedder)
    return embedder


def _cli_for(monkeypatch, tmp_path, name):
    """Point the CLI's profile machinery at the throwaway profiles dir."""
    from zylch.cli import main as cli_main
    from zylch.cli import profiles as pm

    monkeypatch.setattr(pm, "PROFILES_DIR", str(tmp_path))
    monkeypatch.setattr(pm, "ZYLCH_DIR", str(tmp_path))
    monkeypatch.setattr(cli_main, "_configure_logging", lambda: None)
    monkeypatch.setattr(cli_main, "_setup_log_file", lambda: None, raising=False)
    return cli_main.cli


def test_memory_status_and_join_from_the_cli(monkeypatch, tmp_path, stub_embedder):
    from zylch.memory.blob_storage import BlobStorage
    from zylch.memory.company_key import entity_namespace
    from zylch.storage.database import get_session

    a = _boot(monkeypatch, tmp_path, "a", key=None, source=None)
    key_a = current_company_key()
    BlobStorage(get_session, stub_embedder).store_blob(
        a, entity_namespace(key_a), "#IDENTIFIERS\nName: Giulia\n#ABOUT\npallets", "x"
    )
    _boot(monkeypatch, tmp_path, "b", key=None, source=None)
    key_b = current_company_key()
    assert key_b != key_a

    cli = _cli_for(monkeypatch, tmp_path, "b")
    dbm.dispose_engine()
    from zylch.storage.storage import Storage

    Storage._instance = None
    r = CliRunner().invoke(cli, ["-p", "b", "memory-status"])
    assert r.exit_code == 0, r.output
    assert f"memory key:   {key_b}" in r.output and "available:    True" in r.output

    dbm.dispose_engine()
    Storage._instance = None
    r = CliRunner().invoke(cli, ["-p", "b", "memory-join", "--yes", key_a])
    assert r.exit_code == 0, r.output
    assert "joined:" in r.output and "contributors: a@company.test" in r.output
    assert "MEMORY_KEY=" + key_a in (tmp_path / "b" / ".env").read_text()

    dbm.dispose_engine()
    Storage._instance = None
    r = CliRunner().invoke(cli, ["-p", "b", "memory-join", "--yes", "AbCdEfGhIjKlMnOpQrStUv"])
    assert r.exit_code == 2 and "refused" in r.output
