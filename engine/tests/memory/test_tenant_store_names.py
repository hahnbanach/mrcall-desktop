"""Plan M2.2/M2.5: derived host names and the dual-name company store."""

from __future__ import annotations

import os
import re
import sqlite3

import pytest

from zylch import runtime
from zylch.memory import store, tenant_names


@pytest.fixture
def memdir(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_DB_DIR", str(tmp_path / "memory"))
    (tmp_path / "memory").mkdir()
    return tmp_path / "memory"


@pytest.fixture
def serving(monkeypatch):
    monkeypatch.setattr(runtime, "_serving", True)


KEY = "AbCdEfGhIjKlMnOpQrStUv"  # 22 chars, the key shape


def test_names_are_short_lowercase_and_one_way():
    user = tenant_names.unix_user("Gn9IcuHxiZhWEBabcdefghijklmn")
    group = tenant_names.company_group(KEY)
    basename = tenant_names.store_basename(KEY)
    assert re.fullmatch(r"mc-[0-9a-f]{12}", user) and len(user) <= 32
    assert re.fullmatch(r"mc-c-[0-9a-f]{12}", group)
    assert re.fullmatch(r"[0-9a-f]{32}\.db", basename)
    assert KEY not in group and KEY not in basename
    assert tenant_names.company_group(KEY) == tenant_names.company_group(KEY)
    assert tenant_names.company_group(KEY) != tenant_names.company_group(KEY[::-1])


def _touch_db(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sqlite3.connect(path).close()


def test_legacy_store_is_found_and_never_shadowed(memdir, serving):
    legacy = store.legacy_memory_db_path(KEY)
    _touch_db(legacy)
    assert store.memory_db_path(KEY) == legacy
    assert store.store_exists(KEY)
    # opening with create=True must open the legacy file, not make a new one
    engine = store.open_memory_engine(KEY, create=True)
    engine.dispose()
    assert not os.path.exists(store.derived_memory_db_path(KEY))


def test_hosted_new_store_gets_the_derived_name(memdir, serving):
    derived = store.derived_memory_db_path(KEY)
    assert store.memory_db_path(KEY) == derived
    assert derived.startswith(str(memdir / tenant_names.company_group(KEY)))
    assert KEY not in derived
    engine = store.open_memory_engine(KEY, create=True)
    engine.connect().close()  # the file appears at first use
    engine.dispose()
    assert os.path.isfile(derived)


def test_local_new_store_keeps_the_legacy_name(memdir):
    assert store.memory_db_path(KEY) == store.legacy_memory_db_path(KEY)


def test_derived_wins_when_both_exist(memdir):
    _touch_db(store.legacy_memory_db_path(KEY))
    _touch_db(store.derived_memory_db_path(KEY))
    assert store.memory_db_path(KEY) == store.derived_memory_db_path(KEY)


def test_relocate_moves_file_and_sidecars_and_is_idempotent(memdir):
    legacy = store.legacy_memory_db_path(KEY)
    _touch_db(legacy)
    open(legacy + "-wal", "wb").write(b"w")
    moved = store.relocate_store(KEY)
    assert moved == store.derived_memory_db_path(KEY)
    assert os.path.isfile(moved) and os.path.isfile(moved + "-wal")
    assert not os.path.exists(legacy) and not os.path.exists(legacy + "-wal")
    assert store.relocate_store(KEY) is None


def test_relocate_refuses_when_both_exist(memdir):
    _touch_db(store.legacy_memory_db_path(KEY))
    _touch_db(store.derived_memory_db_path(KEY))
    with pytest.raises(store.MemoryUnavailable):
        store.relocate_store(KEY)


def test_zylch_home_moves_the_default_memory_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("MEMORY_DB_DIR", raising=False)
    monkeypatch.setenv("ZYLCH_HOME", str(tmp_path / "h"))
    assert store.memory_dir() == str(tmp_path / "h" / "memory")


def test_hosted_memory_join_rpc_is_an_operator_action(serving):
    import asyncio

    from zylch.rpc.memory_join import memory_join

    out = asyncio.run(memory_join({"key": KEY}, lambda *a, **k: None))
    assert out["ok"] is False and out["operator_action"] is True


def test_relocate_moves_lock_files_too(memdir):
    legacy = store.legacy_memory_db_path(KEY)
    _touch_db(legacy)
    open(legacy + ".sweep.lock", "w").close()
    moved = store.relocate_store(KEY)
    assert os.path.exists(moved + ".sweep.lock") and not os.path.exists(legacy + ".sweep.lock")
    assert not any(KEY in name for name in os.listdir(memdir))
